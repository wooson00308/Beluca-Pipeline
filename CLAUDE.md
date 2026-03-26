# BPE (Beluca Pipeline Engine)

VFX 프로덕션 파이프라인 도구. Nuke(합성)와 ShotGrid(프로젝트 관리)를 연결하는 데스크톱 앱.

## 모듈 구조 (절대 위반 금지)

```
src/bpe/
├── core/          # 순수 로직 (GUI 없음, 표준 라이브러리만)
├── shotgrid/      # ShotGrid API 래퍼 (shotgun_api3 의존)
├── gui/           # PySide6 GUI (데스크톱 앱)
│   ├── tabs/      # 탭별 UI
│   ├── widgets/   # 재사용 위젯
│   └── workers/   # QThread 워커
└── nuke_plugin/   # Nuke 내부 실행 (PySide6 절대 금지)
```

## import 규칙 (반드시 지킬 것)

1. `core/` → 표준 라이브러리만 import. PySide6, shotgun_api3 import 금지.
2. `shotgrid/` → `core/` import 가능. `gui/` import 금지.
3. `gui/` → `core/`, `shotgrid/` import 가능. 비즈니스 로직 직접 구현 금지.
4. `nuke_plugin/` → `core/` import만 가능. PySide6, shotgrid/ import 절대 금지.

위반하면 앱이 빌드에서 터지거나 Nuke에서 크래시 남.

## config 참조 패턴

config.py의 상수(APP_DIR 등)는 기본 인자로 쓰지 말 것. 런타임에 참조해야 테스트가 돌아감.

```python
# 올바른 방법
import bpe.core.config as cfg
def my_func():
    return cfg.APP_DIR / "something"

# 틀린 방법 (테스트에서 monkeypatch 안 먹힘)
from bpe.core.config import APP_DIR
def my_func(path=APP_DIR):  # ← 이러면 안 됨
    return path / "something"
```

## 설정 파일 호환

`~/.setup_pro/` 디렉토리의 JSON 포맷은 기존 BPE v1과 호환되어야 함.
settings.json, presets.json, shot_builder.json 구조를 변경하면 기존 사용자 데이터가 깨짐.

## QThread 규칙

ShotGrid API 호출은 반드시 ShotGridWorker(QThread)로 감싸야 함.
워커 참조는 `self._workers` 리스트에 append해서 GC 방지.

```python
# 올바른 방법
w = ShotGridWorker(func)
w.start()
self._workers.append(w)

# 틀린 방법 (이전 워커가 GC되면서 크래시)
self._worker = ShotGridWorker(func)
self._worker.start()
```

## Python 버전

Python 3.9 호환 필수. Nuke 13이 Python 3.9를 쓰기 때문.

```python
# 모든 파일 최상단에:
from __future__ import annotations

# 타입 힌트는 3.9 호환 형태로:
from typing import Dict, List, Optional, Any
# dict[str, Any] 대신 Dict[str, Any] 사용
```

## 린트

ruff로 린트. line-length 100자. push 전에 반드시:
```bash
ruff check src/ tests/
ruff format src/ tests/
```

## 로깅

디버그 로그는 통합 로거만 사용:
```python
from bpe.core.logging import get_logger
logger = get_logger("모듈이름")
logger.info("메시지")
```
print()로 디버그하지 말 것. 별도 로그 파일 만들지 말 것.

## 파일 I/O

JSON 파일 읽기/쓰기는 반드시 atomic_io 사용:
```python
from bpe.core.atomic_io import read_json_file, write_json_file
```
직접 open()으로 JSON 쓰지 말 것. 네트워크 폴더에서 파일이 깨질 수 있음.

## 에러 처리

ShotGrid 관련 에러는 ShotGridError로 감싸기:
```python
from bpe.shotgrid.errors import ShotGridError
raise ShotGridError("사용자에게 보여줄 메시지")
```

## 테스트

새 기능 추가하면 테스트도 추가. tests/ 구조는 src/bpe/ 구조를 미러링.
```bash
python -m pytest tests/ -v
```

## CI/CD

```
코드 수정 → git push → CI 자동 (lint + test)
                              ↓ 통과
                        개발 계속...
                              ↓ 배포 준비 되면
                        git tag v0.x.x → push → CD 자동 (빌드 + Release)
```

- CI: `.github/workflows/ci.yml` — 매 push/PR마다 Ubuntu/Windows/macOS x Python 3.9/3.11 매트릭스에서 ruff + pytest
- CD: `.github/workflows/release.yml` — `v*` 태그 push 시 PyInstaller 빌드 → GitHub Release 업로드
- 버전: `0.2.x` 현재 개발 단계. 패치 `v0.2.x`, 기능 `v0.3.0`, 안정 `v1.0.0`

## 커밋 메시지 컨벤션

```
<type>: <설명>
```

타입:
- `feat` — 새 기능 (`feat: Shot Builder 폴더 템플릿 선택 구현`)
- `fix` — 버그 수정 (`fix: QThread GC 크래시 수정`)
- `refactor` — 리팩토링 (`refactor: preset 로딩 로직 core/로 분리`)
- `style` — 코드 포맷/린트 (`style: ruff format 적용`)
- `test` — 테스트 추가/수정 (`test: MockShotgun 버전 업로드 테스트 추가`)
- `docs` — 문서 (`docs: README ShotGrid 연결 섹션 추가`)
- `ci` — CI/CD 수정 (`ci: Ubuntu Qt 의존성 추가`)
- `chore` — 기타 잡일 (`chore: .gitignore bpe.spec 예외 추가`)

한글로 쓰되, 끝에 마침표 붙이지 말 것. 한 줄로 끝내는 게 기본.

## push 전 체크리스트

```bash
ruff check src/ tests/       # 린트 에러 0
ruff format src/ tests/      # 포맷 정리
python -m pytest tests/ -q   # 테스트 전부 통과
git push                     # CI가 나머지 검증
```
