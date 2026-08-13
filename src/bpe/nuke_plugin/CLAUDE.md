# Nuke 플러그인 규칙

## 절대 금지

- `from PySide6 import ...` — Nuke는 자체 PySide2를 씀. PySide6 import하면 충돌나서 Nuke가 크래시
- `from bpe.gui import ...` — GUI 모듈 의존 금지
- `from bpe.shotgrid import ...` — SG 모듈 의존 금지

## 허용되는 import

```python
import nuke
import nukescripts
from bpe.core.presets import load_presets
from bpe.core.settings import get_tools_settings
from bpe.core.cache import save_nuke_formats_cache
```

## Nuke 콜백 안전 패턴

beforeRender/afterRender 콜백 안에서 노드 생성/UI 조작은 금지.
반드시 `nuke_defer.execute_deferred()` 사용:

```python
from bpe.nuke_plugin.nuke_defer import execute_deferred

def bpe_after_render():
    # 여기서 노드 생성하면 안 됨
    execute_deferred(_deferred_work)

def _deferred_work():
    # 여기서는 OK
    nuke.createNode("Read")
```

**`nuke.executeDeferred()` 를 쓰지 말 것 — 존재하지 않는 API다.**
Nuke 12/14/17 전부 `executeDeferred` 는 `plugins/nukescripts/utils.py` 에만 있고
`nuke` 네임스페이스에는 `executeInMainThread` 만 있다. `nuke.executeDeferred` 를 쓰면
`AttributeError` 가 나고, beforeRender 콜백에서 터지면 **렌더가 통째로 막힌다**.
`nuke_defer.execute_deferred()` 가 `executeInMainThread` → `nukescripts.executeDeferred`
→ 즉시 실행 순으로 폴백을 처리한다.

## QC Checker 재렌더 방지

`_bpe_qc_approved` set으로 이미 승인된 Write 노드 관리.
이 패턴을 건드리면 무한 렌더 루프 발생.

## 테스트 불가

이 모듈은 `import nuke`가 Nuke 안에서만 가능해서 pytest로 테스트 못 함.
수동 검증 필수: Nuke에서 메뉴 실행 → 프리셋 적용 → 렌더 콜백 확인.
