@echo off
chcp 65001 >nul
cd /d "%~dp0"
python collect_open_meteo_aqi_2025_5_provinces.py
echo.
echo Finished. Check the open_meteo_aqi_2025_output folder.
pause
