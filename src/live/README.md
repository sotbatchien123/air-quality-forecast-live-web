# Live Hourly Collection and Prediction

The live pipeline collects current TomTom traffic, Open-Meteo CAMS Global AQI,
and Open-Meteo weather. It stores one snapshot per location and hour, then runs
the XGBoost hourly model after 12 consecutive snapshots are available.

## Configure TomTom

Set the API key for the current PowerShell session. Do not put the key in source
code or commit it to Git.

```powershell
$env:TOMTOM_API_KEY = "your_tomtom_api_key"
```

Alternatively, read the key from a file outside the repository:

```powershell
python src\live\live_hourly_predictor.py doctor `
  --tomtom-key-file "C:\path\to\key_tom_tom.txt"
```

## Check APIs and model

```powershell
python src\live\live_hourly_predictor.py doctor
```

This checks Open-Meteo weather/AQI, the location manifest, the model bundle, and
whether the TomTom key is configured. It does not write live observations.

## Collect and predict

Run this command once per hour:

```powershell
python src\live\live_hourly_predictor.py run
```

Or run with the external key file:

```powershell
python src\live\live_hourly_predictor.py run `
  --tomtom-key-file "C:\path\to\key_tom_tom.txt"
```

Snapshots are upserted into `data/live/hourly_observations.csv`. After 12 exact
hourly snapshots exist for all supported locations, forecasts are written to
`data/live/predictions` automatically.

TomTom coverage probing currently returns HTTP 400 for Con Dao, Tan Phu in Dong
Nai, and Can Gio. Live collection therefore covers 62 locations and reports the
three exclusions; the offline model and historical datasets remain unchanged.

The standard TomTom Flow Segment endpoint supplies a current traffic snapshot;
it cannot be used to backfill the preceding 12 hours. The collector therefore
waits for genuine live history instead of substituting old project data.

## Run automatically in the background

Start a hidden collector that runs at minute 05 every hour:

```powershell
powershell -ExecutionPolicy Bypass -File src\live\start_live_collector.ps1
```

Run immediately once and then continue with the hourly schedule:

```powershell
powershell -ExecutionPolicy Bypass -File src\live\start_live_collector.ps1 -RunNow
```

Check status or stop the background collector:

```powershell
powershell -ExecutionPolicy Bypass -File src\live\status_live_collector.ps1
powershell -ExecutionPolicy Bypass -File src\live\stop_live_collector.ps1
```

Standard output and errors are written to `data/live/collector_12h.log`. A lock
file prevents duplicate collectors.

## Windows Task Scheduler

For a collector that launches a fresh process each hour, register the included
Windows scheduled task:

```powershell
powershell -ExecutionPolicy Bypass -File src\live\register_live_collector_task.ps1
schtasks /Run /TN DAP391_Live_Hourly_Collector
```

Check status or remove the task:

```powershell
powershell -ExecutionPolicy Bypass -File src\live\status_live_collector_task.ps1
powershell -ExecutionPolicy Bypass -File src\live\unregister_live_collector_task.ps1
```

Scheduled-run logs are appended to `data/live/scheduled_collector.log`.
