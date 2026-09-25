import json
from pathlib import Path

import pytest

from spx_tracker import SpxError, SpxNotFound, TrackingCache, parse_order_info

FIXTURE = Path(__file__).parent / "fixtures" / "order_info.json"


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_sorts_newest_first_and_picks_status():
    res = parse_order_info("SPXVN000000000001", load())
    assert res.tracking_number == "SPXVN000000000001"
    assert res.status == "Đang giao hàng"
    assert [e.description for e in res.events] == [
        "Đơn hàng đang được giao",
        "Đơn hàng đã được lấy thành công",
    ]
    assert res.events[0].location == "Bưu cục Cầu Giấy"
    assert res.events[0].time.utcoffset().total_seconds() == 7 * 3600


def test_parse_error_retcode():
    with pytest.raises(SpxError):
        parse_order_info("X", {"retcode": 10001, "message": "not found"})


def test_parse_empty_data_is_not_found():
    with pytest.raises(SpxNotFound):
        parse_order_info("DEERSTORE1", {"retcode": 0, "data": {}})


def test_cache_roundtrip_and_ttl(tmp_path):
    cache = TrackingCache(str(tmp_path / "c.sqlite3"), ttl_seconds=60)
    assert cache.get("A") is None
    cache.set("A", {"x": "ố"})
    assert cache.get("A") == {"x": "ố"}
    cache.ttl = -1
    assert cache.get("A") is None
    cache.close()
