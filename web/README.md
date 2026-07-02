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
