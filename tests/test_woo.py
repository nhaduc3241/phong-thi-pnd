from datetime import datetime

from spx_tracker.models import Event, SpxError, SpxNotFound, TrackingResult
from spx_tracker.woo import (StateStore, SyncConfig, extract_tracking_number, format_note,
                             is_delivered, real_tracking_number, sync_orders)


def result(status, desc="x", tn="SPXVN061359307249"):
    return TrackingResult(tn, status, [Event(datetime(2026, 9, 25, 10, 0), desc, "Bưu cục A")])


def test_extract_from_preferred_meta():
    order = {"meta_data": [{"key": "spx_tracking", "value": "spxvn061359307249"}]}
    assert extract_tracking_number(order) == "SPXVN061359307249"


def test_extract_from_shipment_tracking_plugin():
    order = {"meta_data": [{"key": "_wc_shipment_tracking_items",
                            "value": [{"tracking_provider": "spx",
                                       "tracking_number": "SPXVN061359307249"}]}]}
    assert extract_tracking_number(order) == "SPXVN061359307249"


def test_extract_from_notes_and_missing():
    assert extract_tracking_number({}, notes=[{"note": "Đã gửi SPX: SPXVN123456789"}]) == "SPXVN123456789"
    assert extract_tracking_number({"customer_note": "giao giờ hành chính"}) is None


def test_real_tracking_number_from_raw():
    r = TrackingResult("DEERSTORE4212", "Đang giao", [],
                       raw={"data": {"sls_tracking_info": {"sls_tn": "SPXVN061359307249"}}})
    assert real_tracking_number(r) == "SPXVN061359307249"


def test_is_delivered_and_note():
    assert is_delivered(result("Giao hàng thành công"))
    assert not is_delivered(result("Đang giao hàng"))
    assert "Bưu cục A" in format_note(result("Đang giao hàng"))


class FakeWoo:
    def __init__(self, orders, notes=None):
        self.orders, self.notes_by_id = orders, notes or {}
        self.added, self.updates, self.list_calls = [], [], []

    def list_orders(self, statuses, after=None):
        self.list_calls.append((tuple(statuses), after))
        return [o for o in self.orders if o.get("status", "processing") in statuses]

    def list_notes(self, oid):
        return self.notes_by_id.get(oid, [])

    def add_note(self, oid, text, customer_note=True):
        self.added.append((oid, text, customer_note))

    def update_order(self, oid, fields):
        self.updates.append((oid, fields))


class FakeTracker:
    def __init__(self, results):
        self.results, self.queries = results, []

    def track(self, tn):
        self.queries.append(tn)
        r = self.results.get(tn, SpxNotFound("no"))
        if isinstance(r, Exception):
            raise r
        return r


def quiet(*_):
    pass


def test_lookup_by_reference_assigns_tracking_and_ships(tmp_path):
    woo = FakeWoo([
        {"id": 4212, "number": "4212", "status": "processing", "meta_data": []},
        {"id": 4213, "number": "4213", "status": "processing", "meta_data": []},
    ])
    tracker = FakeTracker({"DEERSTORE4212": result("Đang giao hàng", tn="SPXVN000000004212")})
    cfg = SyncConfig(ref_prefix="DEERSTORE", shipping_status="shipping",
                     delivered_status="completed")
    rep = sync_orders(woo, tracker, StateStore(str(tmp_path / "s.db")), cfg, log=quiet)

    assert tracker.queries == ["DEERSTORE4212", "DEERSTORE4213"]
    assert rep.assigned == [4212] and rep.no_tracking == [4213] and rep.completed == []
    assert woo.updates == [(4212, {"meta_data": [{"key": "spx_tracking",
                                                  "value": "SPXVN000000004212"}],
                                   "status": "shipping"})]
    assert "SPXVN000000004212" in woo.added[0][1]


def test_existing_tracking_goes_to_delivered(tmp_path):
    woo = FakeWoo([{"id": 7, "number": "7", "status": "shipping",
                    "meta_data": [{"key": "spx_tracking", "value": "SPXVN000000000007"}]}])
    tracker = FakeTracker({"SPXVN000000000007": result("Giao hàng thành công")})
    state = StateStore(str(tmp_path / "s.db"))
    cfg = SyncConfig(ref_prefix="DEERSTORE", shipping_status="shipping",
                     delivered_status="completed")
    rep = sync_orders(woo, tracker, state, cfg, log=quiet)
    assert tracker.queries == ["SPXVN000000000007"]
    assert rep.assigned == [] and rep.completed == [7]
    assert woo.updates == [(7, {"status": "completed"})]


def test_notes_only_on_change_and_errors_reported(tmp_path):
    woo = FakeWoo(
        orders=[
            {"id": 1, "meta_data": [{"key": "spx_tracking", "value": "SPXVN000000001"}]},
            {"id": 2, "meta_data": []},
            {"id": 3, "meta_data": []},
            {"id": 4, "meta_data": [{"key": "spx_tracking", "value": "SPXVN000000004"}]},
        ],
        notes={3: [{"note": "SPXVN000000003"}]},
    )
    tracker = FakeTracker({
        "SPXVN000000001": result("Đang giao hàng"),
        "SPXVN000000003": result("Đang giao hàng"),
        "SPXVN000000004": SpxError("timeout"),
    })
    state = StateStore(str(tmp_path / "s.db"))
    cfg = SyncConfig()
    rep = sync_orders(woo, tracker, state, cfg, log=quiet)
    assert rep.no_tracking == [2] and rep.updated == [1, 3] and len(rep.errors) == 1
    assert woo.updates == []  # không cấu hình trạng thái thì không đổi trạng thái

    woo.added.clear()
    rep = sync_orders(woo, tracker, state, cfg, log=quiet)
    assert rep.updated == [] and woo.added == []


def test_dry_run_writes_nothing(tmp_path):
    woo = FakeWoo([{"id": 1, "number": "1", "status": "processing", "meta_data": []}])
    tracker = FakeTracker({"DEERSTORE1": result("Giao hàng thành công", tn="SPXVN000000000001")})
    rep = sync_orders(woo, tracker, StateStore(str(tmp_path / "s.db")),
                      SyncConfig(ref_prefix="DEERSTORE", shipping_status="shipping",
                                 delivered_status="completed", dry_run=True), log=quiet)
    assert rep.assigned == [1] and rep.completed == [1]
    assert woo.added == [] and woo.updates == []


def test_processing_limited_by_age_shipping_unlimited(tmp_path):
    woo = FakeWoo([
        {"id": 10, "number": "10", "status": "processing", "meta_data": []},
        {"id": 11, "number": "11", "status": "shipping",
         "meta_data": [{"key": "spx_tracking", "value": "SPXVN000000000011"}]},
    ])
    tracker = FakeTracker({"SPXVN000000000011": result("Đang giao hàng")})
    cfg = SyncConfig(ref_prefix="DEERSTORE", shipping_status="shipping", max_age_days=5)
    rep = sync_orders(woo, tracker, StateStore(str(tmp_path / "s.db")), cfg, log=quiet)

    (st1, after1), (st2, after2) = woo.list_calls
    assert st1 == ("processing",) and after1 is not None
    assert 4.9 < (datetime.now() - after1).total_seconds() / 86400 < 5.1
    assert st2 == ("shipping",) and after2 is None
    assert rep.checked == 2
    assert tracker.queries == ["DEERSTORE10", "SPXVN000000000011"]
