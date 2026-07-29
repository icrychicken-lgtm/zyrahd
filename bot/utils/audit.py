"""Audit- und Aktivitäts-Logging."""

from __future__ import annotations

from typing import Any, Optional

from database.manager import get_session
from database.models import ActivityLog, AuditLog, _json_dumps


def write_audit(
    *,
    user_id: int,
    username: str,
    action: str,
    area: str = "general",
    before: Any = "",
    after: Any = "",
    ip_address: str = "",
) -> None:
    before_s = before if isinstance(before, str) else _json_dumps(before)
    after_s = after if isinstance(after, str) else _json_dumps(after)
    with get_session() as session:
        session.add(
            AuditLog(
                user_id=int(user_id),
                username=username or "",
                action=action,
                area=area,
                before_value=before_s or "",
                after_value=after_s or "",
                ip_address=ip_address or "",
            )
        )


def write_activity(kind: str, message: str, meta: Optional[dict] = None) -> None:
    with get_session() as session:
        session.add(
            ActivityLog(
                kind=kind,
                message=message,
                meta_json=_json_dumps(meta or {}),
            )
        )
