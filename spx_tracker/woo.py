"""Đồng bộ trạng thái đơn SPX vào WooCommerce qua REST API (wc/v3).

Worker chạy trên máy có Chromium (VPS hoặc máy ở nhà), không cần chạy trên hosting.
Mỗi lần chạy sẽ:
  1. lấy các đơn WooCommerce đang ở trạng thái cần theo dõi (mặc định: processing)
  2. tìm mã vận đơn SPX trong meta của đơn, ghi chú khách hoặc ghi chú đơn
  3. tra SPX; nếu trạng thái đổi so với lần trước thì thêm ghi chú vào đơn
     (khách thấy được và nhận email từ WooCommerce)
  4. tuỳ chọn: tra theo mã tham chiếu của shop (DEERSTORE<số đơn>) để tự gán mã
     vận đơn, chuyển đơn sang "đang giao" và sang "đã giao" khi SPX báo giao xong
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Protocol

import requests

from .models import SpxError, SpxNotFound, TrackingResult

TRACKING_RE = re.compile(r"\bSPXVN\d{8,}\b", re.IGNORECASE)

DEFAULT_META_KEYS = (
    "spx_tracking",
    "_spx_tracking",
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

    def list_orders(self, statuses: Iterable[str], after: datetime | None = None) -> list[dict]:
        orders, page = [], 1
        while True:
            params = {"status": ",".join(statuses), "per_page": 50, "page": page,
                      "orderby": "date", "order": "desc"}
            if after is not None:
                params["after"] = after.strftime("%Y-%m-%dT%H:%M:%S")
            batch = self._request("GET", "/orders", params=params)
            orders.extend(batch)
            if len(batch) < 50:
                return orders
            page += 1

    def get_order(self, order_id: int) -> dict:
        return self._request("GET", f"/orders/{order_id}")

    def list_notes(self, order_id: int) -> list[dict]:
        return self._request("GET", f"/orders/{order_id}/notes")

    def add_note(self, order_id: int, text: str, customer_note: bool = True) -> None:
        self._request("POST", f"/orders/{order_id}/notes",
                      json={"note": text, "customer_note": customer_note})

    def update_order(self, order_id: int, fields: dict) -> None:
        self._request("PUT", f"/orders/{order_id}", json=fields)


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
    # Đơn mới cần tìm mã vận đơn: chỉ lấy đơn tạo trong max_age_days ngày gần nhất
    statuses: tuple[str, ...] = ("processing",)
    max_age_days: int | None = 5
    meta_keys: tuple[str, ...] = DEFAULT_META_KEYS
    delivered_keywords: tuple[str, ...] = DEFAULT_DELIVERED_KEYWORDS
    # Nếu có, đơn chưa có mã SPX sẽ được tra bằng mã tham chiếu <ref_prefix><số đơn>,
    # ví dụ DEERSTORE4212 cho đơn #4212
    ref_prefix: str = ""
    # Meta key để ghi mã SPX tìm được vào đơn
    tracking_meta_key: str = "spx_tracking"
    # Trạng thái WooCommerce (slug, không có "wc-") khi đã có mã vận đơn / khi đã giao.
    # None = không đổi trạng thái.
    shipping_status: str | None = None
    delivered_status: str | None = None
    customer_note: bool = True
    dry_run: bool = False


@dataclass
class SyncReport:
    checked: int = 0
    no_tracking: list[int] = field(default_factory=list)
    assigned: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    completed: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def real_tracking_number(result: TrackingResult) -> str | None:
    """Mã SPXVN thật trong kết quả (khi tra bằng mã tham chiếu của shop)."""
    return _find_in(result.tracking_number) or _find_in(result.raw)


def sync_orders(woo: WooClient, tracker: Tracker, state: StateStore,
                cfg: SyncConfig, log=print) -> SyncReport:
    report = SyncReport()
    after = (datetime.now() - timedelta(days=cfg.max_age_days)) if cfg.max_age_days else None
    log(f"Đang lấy đơn WooCommerce ({', '.join(cfg.statuses)}"
        f"{f', {cfg.max_age_days} ngày gần nhất' if after else ''})...")
    orders = woo.list_orders(cfg.statuses, after=after)
    # Đơn đang giao thì theo dõi tới khi giao xong, không giới hạn ngày
    if cfg.shipping_status and cfg.shipping_status not in cfg.statuses:
        seen = {o["id"] for o in orders}
        orders += [o for o in woo.list_orders((cfg.shipping_status,)) if o["id"] not in seen]
    log(f"Có {len(orders)} đơn cần kiểm tra")
    for order in orders:
        oid = order["id"]
        report.checked += 1
        tn = extract_tracking_number(order, (cfg.tracking_meta_key, *cfg.meta_keys))
        if tn is None and not cfg.ref_prefix:
            tn = extract_tracking_number({}, (), notes=woo.list_notes(oid))
        query = tn or (f"{cfg.ref_prefix}{order.get('number') or oid}" if cfg.ref_prefix else None)
        if query is None:
            log(f"#{oid}: chưa có mã SPX, bỏ qua")
            report.no_tracking.append(oid)
            continue

        log(f"#{oid}: tra SPX {query}...")
        try:
            result = tracker.track(query)
        except SpxNotFound:
            log(f"#{oid}: SPX chưa có đơn {query}")
            report.no_tracking.append(oid)
            continue
        except SpxError as e:
            report.errors.append(f"#{oid} {query}: {e}")
            log(f"#{oid} {query}: LỖI {e}")
            continue

        changes: dict = {}
        # 1. Gán mã vận đơn tìm được qua mã tham chiếu
        if tn is None:
            tn = real_tracking_number(result)
            if tn is None:
                report.errors.append(f"#{oid} {query}: không thấy mã SPXVN trong kết quả")
                log(f"#{oid}: không thấy mã SPXVN trong kết quả tra {query}")
                continue
            log(f"#{oid}: gán mã vận đơn {tn}")
            changes["meta_data"] = [{"key": cfg.tracking_meta_key, "value": tn}]
            report.assigned.append(oid)

        # SPX đã có đơn (mã mới gán hoặc có sẵn) mà đơn vẫn chưa ở trạng thái đang giao
        if cfg.shipping_status and order.get("status") != cfg.shipping_status:
            changes["status"] = cfg.shipping_status

        # 2. Đã giao
        if cfg.delivered_status and is_delivered(result, cfg.delivered_keywords):
            log(f"#{oid} {tn}: đã giao -> {cfg.delivered_status}")
            changes["status"] = cfg.delivered_status
            report.completed.append(oid)
        elif "status" in changes:
            log(f"#{oid} {tn}: -> {changes['status']}")

        # 3. Ghi chú khi trạng thái SPX thay đổi
        status = result.status or ""
        note_needed = status and status != state.get(oid)
        if note_needed:
            log(f"#{oid} {tn}: {state.get(oid)!r} -> {status!r}")
            report.updated.append(oid)

        if cfg.dry_run:
            continue
        if changes:
            woo.update_order(oid, changes)
        if note_needed:
            result.tracking_number = tn
            woo.add_note(oid, format_note(result), customer_note=cfg.customer_note)
            state.set(oid, tn, status)
    return report
