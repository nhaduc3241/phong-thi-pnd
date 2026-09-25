"""Đồng bộ trạng thái đơn SPX vào WooCommerce qua REST API (wc/v3).

Worker chạy trên máy có Chromium (VPS hoặc máy ở nhà), không cần chạy trên hosting.
Mỗi lần chạy sẽ:
  1. lấy các đơn WooCommerce đang ở trạng thái cần theo dõi (mặc định: processing)
  2. tìm mã vận đơn SPX trong meta của đơn, ghi chú khách hoặc ghi chú đơn
  3. tra SPX; nếu trạng thái đổi so với lần trước thì thêm ghi chú vào đơn
     (khách thấy được và nhận email từ WooCommerce)
  4. tuỳ chọn: chuyển đơn sang "completed" khi SPX báo giao thành công
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

import requests

from .models import SpxError, TrackingResult

TRACKING_RE = re.compile(r"\bSPXVN\d{8,}\b", re.IGNORECASE)

DEFAULT_META_KEYS = (
    "_spx_tracking",
    "spx_tracking",
    "_tracking_number",
    "tracking_number",
    "_wc_shipment_tracking_items",  # plugin Advanced Shipment Tracking
)

DEFAULT_DELIVERED_KEYWORDS = ("giao hàng thành công", "đã giao", "delivered")


class WooClient:
    def __init__(self, base_url: str, key: str, secret: str, auth_in_query: bool = False,
                 timeout: int = 30):
        self.base = base_url.rstrip("/") + "/wp-json/wc/v3"
        self.key, self.secret = key, secret
        # Nhiều hosting chia sẻ bỏ header Authorization; khi đó gửi key qua query string
        self.auth_in_query = auth_in_query
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "spx-tracker-sync/1.0"

    def _request(self, method: str, path: str, params: dict | None = None,
                 json: dict | None = None) -> Any:
        params = dict(params or {})
        auth = None
        if self.auth_in_query:
            params.update(consumer_key=self.key, consumer_secret=self.secret)
        else:
            auth = (self.key, self.secret)
        r = self.session.request(method, self.base + path, params=params, json=json,
                                 auth=auth, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"WooCommerce {method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def list_orders(self, statuses: Iterable[str]) -> list[dict]:
        orders, page = [], 1
        while True:
            batch = self._request("GET", "/orders", params={
                "status": ",".join(statuses), "per_page": 50, "page": page,
                "orderby": "date", "order": "desc",
            })
            orders.extend(batch)
            if len(batch) < 50:
                return orders
            page += 1

    def list_notes(self, order_id: int) -> list[dict]:
        return self._request("GET", f"/orders/{order_id}/notes")

    def add_note(self, order_id: int, text: str, customer_note: bool = True) -> None:
        self._request("POST", f"/orders/{order_id}/notes",
                      json={"note": text, "customer_note": customer_note})

    def set_status(self, order_id: int, status: str) -> None:
        self._request("PUT", f"/orders/{order_id}", json={"status": status})


def _find_in(value: Any) -> str | None:
    if isinstance(value, str):
        m = TRACKING_RE.search(value)
        return m.group(0).upper() if m else None
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        for v in value:
            found = _find_in(v)
            if found:
                return found
    return None


def extract_tracking_number(order: dict, meta_keys: Iterable[str] = DEFAULT_META_KEYS,
                            notes: list[dict] | None = None) -> str | None:
    """Tìm mã SPX: meta ưu tiên → mọi meta khác → ghi chú của khách → ghi chú đơn."""
    meta = order.get("meta_data") or []
    by_key = {m.get("key"): m.get("value") for m in meta if isinstance(m, dict)}
    for k in meta_keys:
        found = _find_in(by_key.get(k))
        if found:
            return found
    for v in by_key.values():
        found = _find_in(v)
        if found:
            return found
    found = _find_in(order.get("customer_note"))
    if found:
        return found
    for n in notes or []:
        found = _find_in(n.get("note"))
        if found:
            return found
    return None


def is_delivered(result: TrackingResult, keywords: Iterable[str] = DEFAULT_DELIVERED_KEYWORDS) -> bool:
    text = " ".join(filter(None, [result.status, result.events[0].description if result.events else None]))
    text = text.lower()
    return any(k.lower() in text for k in keywords)


def format_note(result: TrackingResult) -> str:
    lines = [f"Cập nhật vận chuyển SPX ({result.tracking_number}): {result.status or 'không rõ'}"]
    if result.events:
        ev = result.events[0]
        t = ev.time.strftime("%d/%m/%Y %H:%M") if ev.time else ""
        loc = f" – {ev.location}" if ev.location else ""
        lines.append(f"{t} {ev.description}{loc}".strip())
    return "\n".join(lines)


class StateStore:
    """Nhớ trạng thái đã báo cho từng đơn để chỉ ghi chú khi có thay đổi."""

    def __init__(self, path: str = ".spx_woo_state.sqlite3"):
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS order_state ("
                         " order_id INTEGER PRIMARY KEY, tn TEXT, last_status TEXT)")
        self._db.commit()

    def get(self, order_id: int) -> str | None:
        row = self._db.execute("SELECT last_status FROM order_state WHERE order_id = ?",
                               (order_id,)).fetchone()
        return row[0] if row else None

    def set(self, order_id: int, tn: str, status: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO order_state VALUES (?, ?, ?)",
                         (order_id, tn, status))
        self._db.commit()


class Tracker(Protocol):
    def track(self, tn: str) -> TrackingResult: ...


@dataclass
class SyncConfig:
    statuses: tuple[str, ...] = ("processing",)
    meta_keys: tuple[str, ...] = DEFAULT_META_KEYS
    delivered_keywords: tuple[str, ...] = DEFAULT_DELIVERED_KEYWORDS
    complete_on_delivered: bool = False
    customer_note: bool = True
    dry_run: bool = False


@dataclass
class SyncReport:
    checked: int = 0
    no_tracking: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    completed: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def sync_orders(woo: WooClient, tracker: Tracker, state: StateStore,
                cfg: SyncConfig, log=print) -> SyncReport:
    report = SyncReport()
    for order in woo.list_orders(cfg.statuses):
        oid = order["id"]
        report.checked += 1
        tn = extract_tracking_number(order, cfg.meta_keys)
        if tn is None:
            tn = extract_tracking_number({}, (), notes=woo.list_notes(oid))
        if tn is None:
            report.no_tracking.append(oid)
            continue
        try:
            result = tracker.track(tn)
        except SpxError as e:
            report.errors.append(f"#{oid} {tn}: {e}")
            log(f"#{oid} {tn}: LỖI {e}")
            continue

        status = result.status or ""
        if status and status != state.get(oid):
            log(f"#{oid} {tn}: {state.get(oid)!r} -> {status!r}")
            if not cfg.dry_run:
                woo.add_note(oid, format_note(result), customer_note=cfg.customer_note)
                state.set(oid, tn, status)
            report.updated.append(oid)

        if cfg.complete_on_delivered and is_delivered(result, cfg.delivered_keywords):
            log(f"#{oid} {tn}: đã giao -> completed")
            if not cfg.dry_run:
                woo.set_status(oid, "completed")
            report.completed.append(oid)
    return report
