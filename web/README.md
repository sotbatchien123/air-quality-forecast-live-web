# Web Dashboard

Thư mục này là static site dùng cho GitHub Pages.

## Luồng dữ liệu

```text
GitHub Actions
  -> chạy src/live/github_actions_hourly.py
  -> lấy/predict/upsert TiDB
  -> chạy src/web/export_web_data.py
  -> ghi web/data/dashboard.json
  -> deploy web/ lên GitHub Pages
```

Frontend chỉ đọc JSON tĩnh:

```text
web/data/dashboard.json
```

## Tra cứu lịch sử hourly

Phần `Hourly Model` chỉ mở sẵn 6 giờ dự báo mới nhất để màn hình gọn hơn.
Các giờ còn lại trong `dashboard.json` vẫn được giữ nguyên và có thể tra cứu
bằng ô `Tra cứu giờ khác` theo mẫu `YYYY-MM-DD HH:MM`. Khi chọn một giờ cũ,
KPI, bản đồ, tổng hợp tỉnh/thành và bảng dự báo sẽ cùng chuyển sang giờ đó.

Không đặt DB password, TomTom API key hoặc secret trong file web.

## Chạy local để xem giao diện

```powershell
python -m http.server 8000 -d web
```

Mở:

```text
http://localhost:8000
```

Nếu chưa chạy GitHub Actions, dashboard sẽ hiển thị trạng thái chờ dữ liệu.
