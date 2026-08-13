"""메인 스레드 다음 틱으로 작업을 미루는 헬퍼.

``nuke.executeDeferred`` 는 **존재하지 않는 API** 다. Nuke 12/14/17 전부
``executeDeferred`` 는 ``plugins/nukescripts/utils.py`` 에만 정의돼 있고,
``nuke`` 네임스페이스에는 ``executeInMainThread`` 만 있다. 이 모듈을 거쳐서
호출하면 그 차이를 신경 쓸 필요가 없다.

PySide6 / shotgrid import 금지 (nuke_plugin 규칙).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence

import nuke


def execute_deferred(
    call: Callable[..., Any],
    args: Sequence[Any] = (),
    kwargs: Optional[Dict[str, Any]] = None,
) -> None:
    """``call`` 을 메인 스레드의 다음 틱에서 실행한다.

    ``nuke.executeInMainThread`` → ``nukescripts.executeDeferred`` 순으로 시도하고,
    둘 다 안 되면 즉시 실행한다(예약 실패로 기능이 통째로 사라지는 것보다 낫다).

    Args:
        call: 실행할 callable.
        args: 위치 인자.
        kwargs: 키워드 인자.
    """
    kw: Dict[str, Any] = dict(kwargs or {})
    try:
        nuke.executeInMainThread(call, tuple(args), kw)
        return
    except Exception:
        pass
    try:
        import nukescripts

        nukescripts.executeDeferred(call, tuple(args), kw)
        return
    except Exception:
        pass
    call(*tuple(args), **kw)
