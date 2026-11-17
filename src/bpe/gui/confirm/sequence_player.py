"""컨펌 창 「이어 재생」 — 고른 컷들의 줄인 그림을 뒤에서 풀어 메모리에 쌓아 둔다.

컷을 차례로 한 번씩만 풀고(컷마다 ffmpeg 하나), 다 푼 그림은 이어 재생을 닫을 때까지
들고 있어서 두 바퀴째부터는 끊기지 않는다. 컷마다 원본 첫 장을 같이 읽어, 그 컷에
룩이 입혀졌는지(로그인지)를 그림으로 가린다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from bpe.core.confirm_look import judge_look, sample_grid
from bpe.core.confirm_media import find_org, is_lut_baked, shot_root_from_movie
from bpe.core.confirm_probe import VideoInfo, probe_video
from bpe.core.confirm_sequence import pick_sizes, sequence_bytes
from bpe.core.logging import get_logger
from bpe.core.lut_cube import CubeLut
from bpe.gui.workers.confirm_stream_worker import StreamDecodeWorker

logger = get_logger("gui.confirm.sequence")

_STOP_WAIT_MS = 3000
_PLATE_KEY = "plate"


class SeqCut:
    """이어 볼 컷 하나 — 어느 영상인지와, 풀어 둔 줄인 그림들."""

    def __init__(
        self, row: Dict[str, Any], movie: str, info: VideoInfo, org: Optional[Path]
    ) -> None:
        self.row = dict(row)
        self.movie = movie
        self.info = info
        self.org = org
        self.size: Tuple[int, int] = (0, 0)
        self.count = max(1, int(info.frame_count or 1))
        self.fps = float(info.fps or 24.0)
        self.frames: Dict[int, Any] = {}
        self.name_baked = is_lut_baked(Path(movie).name)
        self.baked: Optional[bool] = None  # 그림으로 가린 결과(None = 아직 모름)
        self.plate: Optional[List[Any]] = None  # 원본 첫 장에서 뽑은 점들
        self.done = False
        self.error = ""

    @property
    def shot(self) -> str:
        return str(self.row.get("shot_code") or Path(self.movie).stem)


def prepare_cuts(rows: List[Dict[str, Any]], resolve: Callable[[Dict[str, Any]], str]) -> Dict:
    """컷마다 영상 파일·규격·원본을 찾는다(뒤에서 돈다). 못 찾은 컷은 건너뛴다."""
    cuts: List[SeqCut] = []
    skipped: List[str] = []
    for row in rows:
        shot = str(row.get("shot_code") or "")
        try:
            movie = resolve(row)
        except Exception as e:  # 한 컷을 못 찾아도 나머지는 본다
            logger.warning("confirm sequence: resolve failed %s: %s", shot, e)
            movie = ""
        info = probe_video(movie) if movie else None
        if not movie or info is None or not info.width or not info.height:
            skipped.append(shot)
            continue
        root = shot_root_from_movie(Path(movie))
        cuts.append(SeqCut(row, movie, info, find_org(root) if root is not None else None))
    return {"cuts": cuts, "skipped": skipped}


class SequencePlayer(QObject):
    """컷들의 줄인 그림 창고. 재생 자체(시계·화면)는 컨펌 창이 한다."""

    frame_ready = Signal(int, int)  # 컷 번호, 프레임 번호
    counts_changed = Signal()  # 실제로 풀린 장 수가 규격과 달랐다
    look_changed = Signal(int)  # 그 컷의 룩 판단이 나왔다
    cut_failed = Signal(int, str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.cuts: List[SeqCut] = []
        self._workers: List[StreamDecodeWorker] = []
        self._next = 0
        self._stopped = False
        self._lut: Optional[CubeLut] = None
        self._default_baked = False

    # ── 준비 ─────────────────────────────────────────────────────

    def load(self, cuts: List[SeqCut], budget_bytes: int) -> bool:
        """컷들을 받아 메모리에 맞는 그림 크기를 정한다. 가장 작게 해도 안 들어가면 ``False``."""
        sizes = pick_sizes(
            [(c.info.width, c.info.height) for c in cuts], [c.count for c in cuts], budget_bytes
        )
        if sizes is None:
            return False
        self.cuts = list(cuts)
        for cut, size in zip(self.cuts, sizes):
            cut.size = size
        return True

    def start(self) -> None:
        self._next = 0
        self._decode_next()

    def counts(self) -> List[int]:
        return [c.count for c in self.cuts]

    def rows(self) -> List[Dict[str, Any]]:
        return [c.row for c in self.cuts]

    def frame(self, cut: int, index: int) -> Optional[Any]:
        if 0 <= cut < len(self.cuts):
            return self.cuts[cut].frames.get(index)
        return None

    def bytes_planned(self) -> int:
        return sequence_bytes([c.size for c in self.cuts], self.counts())

    def index_of(self, row: Dict[str, Any]) -> int:
        """이 줄(샷)이 몇 번째 컷인가. 이어 보는 컷이 아니면 -1."""
        key = row.get("task_id")
        if key is None:
            return -1
        return next((i for i, c in enumerate(self.cuts) if c.row.get("task_id") == key), -1)

    # ── 룩 ───────────────────────────────────────────────────────

    def set_lut(self, lut: Optional[CubeLut], default_baked: bool) -> None:
        """뷰어 룩업과, 그림으로 못 가렸을 때 쓸 기본값(프리셋이 룩을 입혀 내는가)."""
        self._lut = lut
        self._default_baked = bool(default_baked)
        for i, cut in enumerate(self.cuts):
            cut.baked = None
            self._judge(i)

    def lut_wanted(self, cut: int) -> bool:
        """이 컷에 룩업을 씌워야 하나 — 그림 판단이 먼저, 없으면 파일 이름(_lut)·프리셋."""
        if not 0 <= cut < len(self.cuts):
            return False
        c = self.cuts[cut]
        if c.baked is not None:
            return not c.baked
        return not (c.name_baked or self._default_baked)

    def _judge(self, index: int) -> None:
        cut = self.cuts[index]
        if self._lut is None or cut.plate is None or not cut.frames or cut.baked is not None:
            return
        first = cut.frames[min(cut.frames)]
        verdict = judge_look(sample_grid(first, cut.size[0], cut.size[1]), cut.plate, self._lut)
        if verdict.baked is not None:
            cut.baked = verdict.baked
            self.look_changed.emit(index)

    # ── 풀기 ─────────────────────────────────────────────────────

    def _decode_next(self) -> None:
        if self._stopped or self._next >= len(self.cuts):
            return
        index = self._next
        self._next += 1
        cut = self.cuts[index]
        w = StreamDecodeWorker(str(index), cut.movie, cut.size[0], cut.size[1])
        w.frame_ready.connect(self._on_frame)
        w.finished_ok.connect(self._on_done)
        w.failed.connect(self._on_failed)
        self._workers.append(w)
        w.start()
        if cut.org is not None:  # 원본 첫 장 — 이 컷이 로그인지 가리는 데 쓴다
            p = StreamDecodeWorker(
                _PLATE_KEY, str(cut.org), cut.size[0], cut.size[1], frame_count=1
            )
            p.frame_ready.connect(lambda _k, _i, d, c=index: self._on_plate(c, d))
            self._workers.append(p)
            p.start()

    def _on_frame(self, key: str, index: int, data: object) -> None:
        if self._stopped:
            return
        cut_index = int(key)
        cut = self.cuts[cut_index]
        cut.frames[index] = data
        if len(cut.frames) == 1:
            self._judge(cut_index)
        self.frame_ready.emit(cut_index, index)

    def _on_plate(self, cut_index: int, data: object) -> None:
        if self._stopped:
            return
        cut = self.cuts[cut_index]
        samples = sample_grid(data, cut.size[0], cut.size[1])
        if samples:
            cut.plate = samples
            self._judge(cut_index)

    def _on_done(self, key: str, sent: int) -> None:
        if self._stopped:
            return
        cut = self.cuts[int(key)]
        cut.done = True
        if 0 < sent < cut.count:  # 규격에 적힌 것보다 덜 풀렸다 — 풀린 만큼만 컷 길이로 본다
            cut.count = sent
            self.counts_changed.emit()
        self._decode_next()

    def _on_failed(self, key: str, msg: str) -> None:
        if self._stopped or key == _PLATE_KEY:
            return
        index = int(key)
        cut = self.cuts[index]
        cut.error, cut.done = msg, True
        cut.count = len(cut.frames)  # 못 푼 컷은 길이 0 — 재생에서 건너뛴다
        self.counts_changed.emit()
        self.cut_failed.emit(index, msg)
        self._decode_next()

    def stop(self) -> None:
        """풀기를 멈추고 그림을 내려놓는다."""
        self._stopped = True
        for w in self._workers:
            w.stop()
        for w in self._workers:
            try:
                if w.isRunning():
                    w.wait(_STOP_WAIT_MS)
            except RuntimeError:
                pass
        self._workers = []
        for cut in self.cuts:
            cut.frames = {}
