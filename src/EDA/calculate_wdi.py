import pandas as pd
import numpy as np
import os

print("===== WEATHER DATA PREPROCESSING PIPELINE =====")

# ======================================
# 1. FILE PATHS
# ======================================

INPUT_FILE = "data/raw/weather/hcm_weather_2025.csv"

OUTPUT_FILE = "data/processed/weather/hcm_weather_WDI_by_hour.csv"

# Tạo thư mục output nếu chưa tồn tại
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

# ======================================
# 2. LOAD DATA
# ======================================

df = pd.read_csv(INPUT_FILE)

print(f"\nLoaded: {INPUT_FILE}")
print("Dataset shape:", df.shape)

# ======================================
# 3. AUTO DETECT COLUMNS
# ======================================

def find_column(keywords):
    for col in df.columns:
        for key in keywords:
            if key.lower() in col.lower():
                return col
    return None

wind_col = find_column(["wind"])
rain_col = find_column(["rain", "precip"])
humidity_col = find_column(["humidity"])
temp_col = find_column(["temp"])

print("\nDetected columns:")
print("Wind:", wind_col)
print("Rain:", rain_col)
print("Humidity:", humidity_col)
print("Temperature:", temp_col)

# ======================================
# 4. HANDLE MISSING VALUES
# ======================================

df[wind_col] = df[wind_col].fillna(df[wind_col].mean())
df[rain_col] = df[rain_col].fillna(df[rain_col].mean())
df[humidity_col] = df[humidity_col].fillna(df[humidity_col].mean())
df[temp_col] = df[temp_col].fillna(df[temp_col].mean())

# ======================================
# 5. MIN-MAX NORMALIZATION
# ======================================

def normalize(series):
    return (series - series.min()) / (series.max() - series.min())

wind_norm = normalize(df[wind_col])
rain_norm = normalize(df[rain_col])
humidity_norm = normalize(df[humidity_col])
temp_norm = normalize(df[temp_col])

# ======================================
# 6. WEATHER DISPERSION INDEX (WDI)
# ======================================

WDI = (wind_norm + rain_norm) / (humidity_norm + temp_norm)

WDI = WDI.replace([np.inf, -np.inf], np.nan)
WDI = WDI.fillna(0)

# ======================================
# 7. CREATE CLEAN DATASET
# ======================================

clean_df = pd.DataFrame({
    "date": df["date"],
    "hour": df["hour"],
    "WDI": WDI.round(3)
})

# ======================================
# 8. EXPORT CSV
# ======================================

clean_df.to_csv(OUTPUT_FILE, index=False)

print(f"\nSaved: {OUTPUT_FILE}")

print("\nPreview:")
print(clean_df.head())

print(f"\nTotal rows: {len(clean_df):,}")

print("\nPipeline completed successfully.")