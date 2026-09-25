from datetime import datetime

from spx_tracker.models import Event, SpxError, TrackingResult
from spx_tracker.woo import (StateStore, SyncConfig, extract_tracking_number, format_note,
                             is_delivered, sync_orders)


def result(status, desc="x"):
    return TrackingResult("SPXVN061359307249", status,
                          [Event(datetime(2026, 9, 25, 10, 0), desc, "Bưu cục A")])


def test_extract_from_preferred_meta():
    order = {"meta_data": [{"key": "_spx_tracking", "value": "spxvn061359307249"}]}
    assert extract_tracking_number(order) == "SPXVN061359307249"


def test_extract_from_shipment_tracking_plugin():
    order = {"meta_data": [{"key": "_wc_shipment_tracking_items",
                            "value": [{"tracking_provider": "spx",
                                       "tracking_number": "SPXVN061359307249"}]}]}
    assert extract_tracking_number(order) == "SPXVN061359307249"


def test_extract_from_notes_and_missing():
    assert extract_tracking_number({}, notes=[{"note": "Đã gửi SPX: SPXVN123456789"}]) == "SPXVN123456789"
    assert extract_tracking_number({"customer_note": "giao giờ hành chính"}) is None


def test_is_delivered_and_note():
    assert is_delivered(result("Giao hàng thành công"))
    assert not is_delivered(result("Đang giao hàng"))
    assert "Bưu cục A" in format_note(result("Đang giao hàng"))


class FakeWoo:
    def __init__(self, orders, notes=None):
        self.orders, self.notes_by_id = orders, notes or {}
        self.added, self.statuses = [], []

    def list_orders(self, statuses):
        return self.orders

    def list_notes(self, oid):
        return self.notes_by_id.get(oid, [])

    def add_note(self, oid, text, customer_note=True):
        self.added.append((oid, text, customer_note))

    def set_status(self, oid, status):
        self.statuses.append((oid, status))


class FakeTracker:
    def __init__(self, results):
        self.results = results

    def track(self, tn):
        r = self.results[tn]
        if isinstance(r, Exception):
            raise r
        return r


def test_sync_only_notes_on_change_and_completes(tmp_path):
    woo = FakeWoo(
        orders=[
            {"id": 1, "meta_data": [{"key": "_spx_tracking", "value": "SPXVN000000001"}]},
            {"id": 2, "meta_data": []},
            {"id": 3, "meta_data": []},
            {"id": 4, "meta_data": [{"key": "_spx_tracking", "value": "SPXVN000000004"}]},
        ],
        notes={3: [{"note": "SPXVN000000003"}]},
    )
    tracker = FakeTracker({
        "SPXVN000000001": result("Đang giao hàng"),
        "SPXVN000000003": result("Giao hàng thành công"),
        "SPXVN000000004": SpxError("timeout"),
    })
    state = StateStore(str(tmp_path / "s.sqlite3"))
    cfg = SyncConfig(complete_on_delivered=True)

    rep = sync_orders(woo, tracker, state, cfg, log=lambda *_: None)
    assert rep.checked == 4
    assert rep.no_tracking == [2]
    assert rep.updated == [1, 3]
    assert rep.completed == [3]
    assert len(rep.errors) == 1
    assert woo.statuses == [(3, "completed")]

    # Lần chạy thứ 2, trạng thái không đổi: không ghi chú lại
    woo.added.clear()
    rep = sync_orders(woo, tracker, state, cfg, log=lambda *_: None)
    assert rep.updated == []
    assert woo.added == []


def test_dry_run_writes_nothing(tmp_path):
    woo = FakeWoo([{"id": 1, "meta_data": [{"key": "_spx_tracking", "value": "SPXVN000000001"}]}])
    tracker = FakeTracker({"SPXVN000000001": result("Giao hàng thành công")})
    rep = sync_orders(woo, tracker, StateStore(str(tmp_path / "s.sqlite3")),
                      SyncConfig(dry_run=True, complete_on_delivered=True), log=lambda *_: None)
    assert rep.updated == [1] and rep.completed == [1]
    assert woo.added == [] and woo.statuses == []
