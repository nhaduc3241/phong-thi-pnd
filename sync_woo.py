"""Chạy một lượt đồng bộ SPX → WooCommerce. Dùng với cron (Linux) hoặc Task Scheduler (Windows).

Cấu hình đặt trong file .env (xem .env.example) hoặc biến môi trường.

    python sync_woo.py            # chạy thật
    python sync_woo.py --dry-run  # chỉ in ra, không ghi vào WooCommerce
"""

import argparse
import json
import os
import sys
from pathlib import Path

from spx_tracker import SpxTracker, TrackingCache
from spx_tracker.woo import (DEFAULT_DELIVERED_KEYWORDS, DEFAULT_META_KEYS, StateStore,
                             SyncConfig, WooClient, sync_orders)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    return tuple(x.strip() for x in raw.split(",") if x.strip()) if raw else default


def env_bool(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


def inspect_order(woo: WooClient, order_id: int) -> int:
    order = woo.get_order(order_id)
    print(f"Đơn #{order_id} | trạng thái: {order.get('status')} | "
          f"vận chuyển: {[l.get('method_title') for l in order.get('shipping_lines', [])]}")
    print(f"Ghi chú của khách: {order.get('customer_note')!r}")
    print("\n--- meta_data ---")
    for m in order.get("meta_data", []):
        print(f"{m.get('key')} = {json.dumps(m.get('value'), ensure_ascii=False)[:200]}")
    print("\n--- ghi chú đơn ---")
    for n in woo.list_notes(order_id):
        print(f"[{n.get('date_created')}] {n.get('note')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--inspect", type=int, metavar="ORDER_ID",
                    help="In meta và ghi chú của một đơn để tìm chỗ lưu mã vận đơn")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    os.chdir(here)  # để cache/profile nằm cạnh script khi chạy từ cron
    load_dotenv(here / ".env")

    missing = [k for k in ("WOO_URL", "WOO_KEY", "WOO_SECRET") if not os.environ.get(k)]
    if missing:
        print("Thiếu cấu hình:", ", ".join(missing), "(xem .env.example)", file=sys.stderr)
        return 2

    woo = WooClient(os.environ["WOO_URL"], os.environ["WOO_KEY"], os.environ["WOO_SECRET"],
                    auth_in_query=env_bool("WOO_AUTH_IN_QUERY"))
    if args.inspect:
        return inspect_order(woo, args.inspect)

    cfg = SyncConfig(
        statuses=env_list("WOO_STATUSES", ("processing",)),
        meta_keys=env_list("WOO_TRACKING_META_KEYS", DEFAULT_META_KEYS),
        delivered_keywords=env_list("SPX_DELIVERED_KEYWORDS", DEFAULT_DELIVERED_KEYWORDS),
        complete_on_delivered=env_bool("COMPLETE_ON_DELIVERED"),
        customer_note=not env_bool("PRIVATE_NOTES"),
        dry_run=args.dry_run,
    )

    with SpxTracker(headless=not args.headful, cache=TrackingCache()) as tracker:
        report = sync_orders(woo, tracker, StateStore(), cfg)

    print(f"Đã kiểm tra {report.checked} đơn | cập nhật {len(report.updated)} | "
          f"hoàn tất {len(report.completed)} | không có mã SPX {len(report.no_tracking)} | "
          f"lỗi {len(report.errors)}")
    if report.no_tracking:
        print("Đơn chưa có mã SPX:", ", ".join(f"#{i}" for i in report.no_tracking))
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
