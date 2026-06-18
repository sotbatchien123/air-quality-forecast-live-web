OPEN-METEO AQI 2025 — FIVE SOUTHERN VIETNAMESE PROVINCES
=========================================================

Scope
-----
Period: 2025-01-01 00:00 through 2025-12-31 23:00
Timezone: Asia/Ho_Chi_Minh
Administrative layout: old province/district boundaries
Locations: 65 representative points

Provinces/city
---------------
- Hồ Chí Minh: 22 locations, 192,720 expected rows
- Long An: 15 locations, 131,400 expected rows
- Bà Rịa - Vũng Tàu: 8 locations, 70,080 expected rows
- Tây Ninh: 9 locations, 78,840 expected rows
- Đồng Nai: 11 locations, 96,360 expected rows
- Total: 569,400 expected rows

How to run on Windows
---------------------
Option 1: Double-click:
    run_collect_open_meteo_aqi_2025.bat

Option 2: PowerShell or CMD:
    python collect_open_meteo_aqi_2025_5_provinces.py

No pip installation or API key is required.

Test without downloading
------------------------
    python collect_open_meteo_aqi_2025_5_provinces.py --dry-run

Test one location
-----------------
    python collect_open_meteo_aqi_2025_5_provinces.py --only-location Quan_1

Resume after interruption
-------------------------
Run the same command again. Complete location files are automatically skipped.

Output files
------------
open_meteo_aqi_2025_output/
  aqi_ho_chi_minh_2025_open_meteo.csv
  aqi_long_an_2025_open_meteo.csv
  aqi_ba_ria_vung_tau_2025_open_meteo.csv
  aqi_tay_ninh_2025_open_meteo.csv
  aqi_dong_nai_2025_open_meteo.csv
  collection_report.csv
  dataset_metadata.json
  locations_5_provinces_old_boundaries.csv
  open_meteo_aqi_2025_5_provinces.zip
  raw_locations/

Main CSV columns
----------------
date, hour, datetime,
province, province_slug, source_traffic_file, location_name,
lat, lon, model_lat, model_lon, elevation, timezone, source_model,
pm10, pm2_5, carbon_monoxide, nitrogen_dioxide,
sulphur_dioxide, ozone,
us_aqi and six component US-AQI columns.

Units and interpretation
------------------------
- Pollutant concentrations are reported in micrograms per cubic metre.
- us_aqi is the United States AQI, not Vietnam's VN_AQI.
- The source is CAMS Global modeled gridded data through Open-Meteo.
  It is not direct monitoring-station observation data.
- CAMS Global has a relatively coarse grid, so nearby districts may receive
  identical or very similar values.
- Keep pollutant concentration columns if VN_AQI will be calculated later.

Merge with traffic data
-----------------------
Use these keys:
    date + hour + location_name

The location names and coordinates were kept consistent with the existing
old-boundary traffic mapping files.

Attribution
-----------
Air-quality data: Open-Meteo Air Quality API
Underlying model: CAMS Global Atmospheric Composition Forecast
