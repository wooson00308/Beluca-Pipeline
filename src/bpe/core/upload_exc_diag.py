"""sg.upload() 실패 시 원인(SSL·URLError 체인)을 NDJSON/로그용 dict로 정리 — 비밀·토큰 없음."""

from __future__ import annotations

from typing import Any, Dict


def sg_upload_exception_diag(exc: BaseException, *, msg_max: int = 480) -> Dict[str, Any]:
    """urllib/SSL 체인을 얕게 펼쳐 진단용 필드만 담는다."""

    def _clip(s: str) -> str:
        t = (s or "").replace("\r", " ").replace("\n", " ")
        return t if len(t) <= msg_max else t[:msg_max]

    out: Dict[str, Any] = {
        "exc_type": type(exc).__name__,
        "exc_msg": _clip(str(exc)),
    }
    reason = getattr(exc, "reason", None)
    if reason is not None:
        out["reason_type"] = type(reason).__name__
        out["reason_msg"] = _clip(str(reason))

    chain = exc.__cause__ if exc.__cause__ is not None else exc.__context__
    if chain is not None:
        out["chain_type"] = type(chain).__name__
        out["chain_msg"] = _clip(str(chain))
        ch_reason = getattr(chain, "reason", None)
        if ch_reason is not None:
            out["chain_reason_type"] = type(ch_reason).__name__
            out["chain_reason_msg"] = _clip(str(ch_reason))

    return out
