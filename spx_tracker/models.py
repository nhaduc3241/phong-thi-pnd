"""Mô hình dữ liệu và parser cho JSON trả về từ API get_order_info của SPX.

Schema của SPX không có tài liệu công khai, nên parser đọc phòng thủ bằng .get()
và thử nhiều tên trường khác nhau. Toàn bộ JSON gốc luôn được giữ trong `raw`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

VN_TZ = timezone(timedelta(hours=7))


class SpxError(Exception):
    """Không tra được SPX (lỗi mạng, bị chặn, dữ liệu không đọc được)."""


class SpxNotFound(SpxError):
    """SPX trả lời nhưng không có đơn với mã này (retcode khác 0 hoặc không có dữ liệu)."""


@dataclass
class Event:
    time: datetime | None
    description: str
    location: str | None = None


@dataclass
class TrackingResult:
    tracking_number: str
    status: str | None
    events: list[Event] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and value > 0:
        # SPX thường trả unix timestamp (giây); phòng trường hợp mili giây
        if value > 1e12:
            value = value / 1000
        return datetime.fromtimestamp(value, tz=VN_TZ)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_location(rec: dict) -> str | None:
    loc = rec.get("current_location")
    if isinstance(loc, dict):
        return _first(loc, "location_name", "full_address")
    return _first(rec, "location_name", "location")


def parse_order_info(tracking_number: str, payload: dict[str, Any]) -> TrackingResult:
    retcode = payload.get("retcode", payload.get("code", 0))
    if retcode not in (0, None):
        raise SpxNotFound(f"SPX retcode={retcode}: {payload.get('message')}")

    data = payload.get("data") or {}
    info = data.get("sls_tracking_info") or data
    records = info.get("records") or info.get("tracking_list") or []

    if not records and not _first(info, "sls_tn", "spx_tn"):
        raise SpxNotFound("SPX không trả dữ liệu cho mã này")

    events = [
        Event(
            time=_parse_time(_first(rec, "actual_time", "timestamp", "time")),
            description=_first(rec, "buyer_description", "description", "tracking_name") or "",
            location=_parse_location(rec),
        )
        for rec in records
        if isinstance(rec, dict)
    ]
    # Mới nhất lên đầu
    events.sort(key=lambda e: e.time or datetime.min.replace(tzinfo=VN_TZ), reverse=True)

    status = None
    if records:
        latest = max(
            (r for r in records if isinstance(r, dict)),
            key=lambda r: _first(r, "actual_time", "timestamp") or 0,
        )
        status = _first(latest, "milestone_name", "tracking_name", "buyer_description")

    return TrackingResult(
        tracking_number=_first(info, "sls_tn", "spx_tn") or tracking_number,
        status=status,
        events=events,
        raw=payload,
    )
