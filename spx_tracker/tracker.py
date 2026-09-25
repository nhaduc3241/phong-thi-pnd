"""Tra cứu đơn SPX bằng Chromium thật (Playwright).

Không tự dựng request tới API. Script mở trang tra cứu công khai của SPX và bắt
response JSON mà chính trang đó gọi tới `get_order_info`. Cookie và token chống bot
đều do JS của SPX tự sinh, giống khi một người mở trang bằng trình duyệt.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

from .cache import TrackingCache
from .models import SpxError, TrackingResult, parse_order_info

TRACK_PAGE_URL = "https://spx.vn/track?{tn}"
API_MARKER = "get_order_info"
API_URL = "/shipment/order/open/order/get_order_info?spx_tn={tn}&language_code=vi"


class SpxTracker:
    def __init__(
        self,
        headless: bool = True,
        profile_dir: str = ".spx_profile",
        min_interval: float = 4.0,
        timeout_ms: int = 30_000,
        retries: int = 2,
        cache: TrackingCache | None = None,
    ):
        self.headless = headless
        self.profile_dir = profile_dir
        self.min_interval = min_interval
        self.timeout_ms = timeout_ms
        self.retries = retries
        self.cache = cache
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None
        self._last_request = 0.0

    # --- vòng đời trình duyệt -------------------------------------------------

    def __enter__(self) -> "SpxTracker":
        self._pw = sync_playwright().start()
        self._open_context(self.headless)
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _open_context(self, headless: bool) -> None:
        if self._ctx is not None:
            self._ctx.close()
        # Profile persistent giữ cookie giữa các lần chạy nên ít bị thử thách lại
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=headless,
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            viewport={"width": 1366, "height": 768},
        )

    def close(self) -> None:
        if self._ctx is not None:
            self._ctx.close()
            self._ctx = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    # --- tra cứu ---------------------------------------------------------------

    def track(self, tn: str) -> TrackingResult:
        tn = tn.strip().upper()
        if self.cache is not None:
            cached = self.cache.get(tn)
            if cached is not None:
                return parse_order_info(tn, cached)

        payload = self._fetch_with_retry(tn)
        result = parse_order_info(tn, payload)
        if self.cache is not None:
            self.cache.set(tn, payload)
        return result

    def _fetch_with_retry(self, tn: str) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._fetch(tn)
            except (PlaywrightTimeout, SpxError, ValueError) as e:
                last_err = e
                if attempt == self.retries:
                    break
                time.sleep(2 ** (attempt + 1))
                # Lần thử cuối: mở cửa sổ thật nếu chế độ headless bị chặn
                if self.headless and attempt == self.retries - 1:
                    self._open_context(headless=False)
        raise SpxError(f"Không tra được {tn}: {last_err}") from last_err

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _fetch(self, tn: str) -> dict[str, Any]:
        if self._ctx is None:
            raise RuntimeError("Dùng SpxTracker trong khối `with SpxTracker() as t:`")
        self._throttle()
        # Dùng lại tab có sẵn (tab about:blank lúc mở trình duyệt) thay vì mở tab mới
        page: Page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        try:
            with page.expect_response(
                lambda r: API_MARKER in r.url and tn in r.url,
                timeout=self.timeout_ms,
            ) as resp_info:
                page.goto(TRACK_PAGE_URL.format(tn=tn), wait_until="domcontentloaded")
        except PlaywrightTimeout:
            # Trang tra cứu không tự gọi API (ví dụ không nhận mã tham chiếu của shop):
            # gọi API ngay trong tab đang mở spx.vn, dùng cookie của phiên hiện tại
            return self._fetch_in_page(page, tn)
        resp = resp_info.value
        if resp.status != 200:
            raise SpxError(f"HTTP {resp.status}")
        return resp.json()

    def _fetch_in_page(self, page: Page, tn: str) -> dict[str, Any]:
        if not page.url.startswith("https://spx.vn"):
            page.goto("https://spx.vn/", wait_until="domcontentloaded")
        res = page.evaluate(
            """async (url) => {
                const r = await fetch(url, {credentials: "include"});
                return {status: r.status, text: await r.text()};
            }""",
            API_URL.format(tn=quote(tn)),
        )
        if res["status"] != 200:
            raise SpxError(f"HTTP {res['status']}")
        try:
            return json.loads(res["text"])
        except ValueError as e:
            raise SpxError(f"SPX trả về không phải JSON: {res['text'][:120]!r}") from e
