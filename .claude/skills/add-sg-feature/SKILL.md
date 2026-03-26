---
name: add-sg-feature
description: ShotGrid API를 사용하는 새 기능 추가 절차. 모듈 함수, MockShotgun 테스트, ShotGridWorker GUI 연결까지 안내.
---

# ShotGrid 기능 추가하기

ShotGrid API를 사용하는 새 기능을 추가할 때 따라야 할 절차.

## 1. shotgrid/ 모듈에 함수 추가

적절한 모듈에 함수를 추가:
- `projects.py` — 프로젝트 관련
- `shots.py` — 샷 관련
- `tasks.py` — Task 관련
- `users.py` — 사용자 관련
- `versions.py` — Version/업로드 관련
- `parser.py` — 파일명 파싱

```python
from __future__ import annotations
from typing import Any, Dict, List, Optional
from bpe.core.logging import get_logger
from bpe.shotgrid.errors import ShotGridError

logger = get_logger("shotgrid.모듈명")

def my_new_function(sg: Any, ...) -> ...:
    """sg 인스턴스를 첫 번째 인자로 받는다."""
    try:
        result = sg.find("EntityType", filters, fields)
        return result
    except Exception as e:
        logger.error("설명: %s", e)
        raise ShotGridError("사용자 메시지") from e
```

## 2. 테스트 작성

`tests/shotgrid/`에 테스트 추가. MockShotgun 사용:

```python
from tests.shotgrid.mock_sg import MockShotgun

def test_my_function():
    sg = MockShotgun()
    sg._add_entity("Shot", {"id": 1, "code": "TEST_001"})
    result = my_new_function(sg, ...)
    assert result == ...
```

## 3. GUI에서 호출

UI 스레드에서 직접 호출 금지. 반드시 ShotGridWorker:

```python
from bpe.gui.workers.sg_worker import ShotGridWorker
from bpe.shotgrid.client import get_default_sg
from bpe.shotgrid.모듈명 import my_new_function

def _on_button_click(self):
    def _fetch():
        sg = get_default_sg()
        return my_new_function(sg, ...)

    w = ShotGridWorker(_fetch)
    w.finished.connect(self._on_result)
    w.error.connect(lambda e: self._log(f"오류: {e}"))
    w.start()
    self._workers.append(w)  # GC 방지
```

## 4. 체크리스트

- [ ] sg 인스턴스를 인자로 받음 (전역 상태 X)
- [ ] ShotGridError로 에러 감싸기
- [ ] get_logger로 로깅
- [ ] MockShotgun으로 테스트
- [ ] GUI에서 ShotGridWorker로 호출
- [ ] self._workers.append(w)
- [ ] pytest 통과
