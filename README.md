# spx_tracker: tra cứu trạng thái đơn SPX (Shopee Express)

Endpoint `https://spx.vn/shipment/order/open/order/get_order_info?spx_tn=...` chặn
request không đến từ trình duyệt thật, vì trang tra cứu tự sinh cookie/token chống bot bằng JS.
Thư viện này **không tự dựng request** mà mở trang tra cứu công khai bằng Chromium thật
(Playwright), rồi bắt JSON mà chính trang đó gọi tới `get_order_info`.

## Cài đặt

```bash
pip install -r requirements.txt
playwright install chromium
```

## Dùng từ dòng lệnh

```bash
python cli.py SPXVN061359307249
python cli.py SPXVN061359307249 --headful            # hiện cửa sổ để xem trang
python cli.py SPXVN061359307249 --save-raw raw.json  # lưu JSON gốc
```

## Tích hợp vào app

```python
from spx_tracker import SpxTracker, TrackingCache

with SpxTracker(headless=True, cache=TrackingCache(ttl_seconds=1800)) as t:
    for tn in ["SPXVN061359307249", "SPXVN..."]:
        res = t.track(tn)
        print(res.tracking_number, res.status)
        for ev in res.events:          # mới nhất lên đầu
            print(ev.time, ev.description, ev.location)
```

- Mỗi lần tra mất vài giây, nên chạy trong worker hoặc cron (ví dụ mỗi 30–60 phút cho các đơn
  chưa giao xong), đừng gọi đồng bộ trong request web.
- Có sẵn giới hạn tốc độ (`min_interval`, mặc định 4 giây giữa 2 lần tra) và cache SQLite.
  Đừng hạ các giá trị này để quét hàng loạt, vì sẽ dễ bị chặn IP.
- Cookie được giữ trong thư mục `.spx_profile/` để các lần sau ít bị thử thách lại.

## Nếu không chạy được

- **Timeout**: chạy `--headful` để xem trang. Có thể SPX đã đổi URL trang tra cứu (xem
  `TRACK_PAGE_URL` trong `spx_tracker/tracker.py`), hoặc trang bắt nhập mã vào ô tìm kiếm.
  Khi đó thêm `page.fill(...)` và `page.click(...)` vào `_fetch`.
- **Thiếu dữ liệu hoặc sai trường**: schema JSON của SPX không có tài liệu công khai.
  Chạy `--save-raw`, chép file vào `tests/fixtures/order_info.json` (fixture hiện tại là
  dữ liệu giả), rồi chỉnh `spx_tracker/models.py`.

## Cách chính thức

Nếu shop bán trên Shopee, API ổn định và được phép dùng là **Shopee Open Platform**
(`v2.logistics.get_tracking_info`, cần partner_id và token của shop). Nên chuyển sang API này khi
có quyền, vì cách dùng trình duyệt có thể hỏng bất cứ lúc nào SPX đổi giao diện.

## Test

```bash
pytest
```
