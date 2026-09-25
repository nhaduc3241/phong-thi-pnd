"""Tra cứu đơn SPX từ dòng lệnh.

    python cli.py SPXVN061359307249 [--headful] [--save-raw out.json]
"""

import argparse
import json
import sys

from spx_tracker import SpxError, SpxTracker, TrackingCache


def main() -> int:
    ap = argparse.ArgumentParser(description="Tra cứu trạng thái đơn SPX")
    ap.add_argument("tracking_numbers", nargs="+")
    ap.add_argument("--headful", action="store_true", help="Hiện cửa sổ trình duyệt")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--save-raw", help="Lưu JSON gốc (của mã đầu tiên) ra file")
    args = ap.parse_args()

    cache = None if args.no_cache else TrackingCache()
    code = 0
    with SpxTracker(headless=not args.headful, cache=cache) as tracker:
        for i, tn in enumerate(args.tracking_numbers):
            try:
                res = tracker.track(tn)
            except SpxError as e:
                print(f"[{tn}] LỖI: {e}", file=sys.stderr)
                code = 1
                continue
            print(f"== {res.tracking_number}: {res.status or '(không rõ)'}")
            for ev in res.events:
                t = ev.time.strftime("%d/%m/%Y %H:%M") if ev.time else "?"
                loc = f" [{ev.location}]" if ev.location else ""
                print(f"  {t}  {ev.description}{loc}")
            if args.save_raw and i == 0:
                with open(args.save_raw, "w", encoding="utf-8") as f:
                    json.dump(res.raw, f, ensure_ascii=False, indent=2)
    return code


if __name__ == "__main__":
    sys.exit(main())
