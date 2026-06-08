import pandas as pd
import os

# =====================================================
# CONFIG
# =====================================================

INPUT_FILE = "data/raw/traffic/traffic_data2025_part3.csv"

SORTED_FILE = "data/raw/traffic/traffic_data2025_part3_sorted.csv"

DISTRICT_FOLDER = "data/raw/traffic/district_files"

os.makedirs(DISTRICT_FOLDER, exist_ok=True)

# =====================================================
# LOAD DATA
# =====================================================

print("Loading data...")

df = pd.read_csv(INPUT_FILE)

print(f"Total rows: {len(df):,}")

# =====================================================
# SORT BY DISTRICT -> DATE -> HOUR
# =====================================================

print("Sorting...")

df_sorted = df.sort_values(
    by=["location_name", "date", "hour"]
).reset_index(drop=True)

df_sorted.to_csv(
    SORTED_FILE,
    index=False
)

print(f"Saved sorted file: {SORTED_FILE}")

# =====================================================
# CHECK DUPLICATES
# =====================================================

print("\n" + "=" * 60)
print("DUPLICATE CHECK")
print("=" * 60)

duplicates = df_sorted[
    df_sorted.duplicated(
        subset=["location_name", "date", "hour"],
        keep=False
    )
]

print(f"Duplicate rows found: {len(duplicates):,}")

if len(duplicates) > 0:

    duplicate_file = (
        "data/raw/traffic/duplicate_records.csv"
    )

    duplicates.to_csv(
        duplicate_file,
        index=False
    )

    print(
        f"Duplicate records saved to:\n"
        f"{duplicate_file}"
    )

    print("\nDuplicate count by district:")

    dup_summary = (
        duplicates
        .groupby("location_name")
        .size()
        .sort_values(ascending=False)
    )

    print(dup_summary)

else:

    print("No duplicates found.")

# =====================================================
# RECORD COUNT PER DISTRICT
# =====================================================

print("\n" + "=" * 60)
print("RECORD COUNT BY DISTRICT")
print("=" * 60)

district_counts = (
    df_sorted
    .groupby("location_name")
    .size()
    .sort_values()
)

print(district_counts)

# =====================================================
# EXPORT EACH DISTRICT
# =====================================================

print("\n" + "=" * 60)
print("EXPORT DISTRICT FILES")
print("=" * 60)

for district in sorted(df_sorted["location_name"].unique()):

    district_df = (
        df_sorted[
            df_sorted["location_name"] == district
        ]
        .sort_values(
            by=["date", "hour"]
        )
        .reset_index(drop=True)
    )

    output_path = os.path.join(
        DISTRICT_FOLDER,
        f"{district}.csv"
    )

    district_df.to_csv(
        output_path,
        index=False
    )

print(
    f"District files saved to:\n"
    f"{DISTRICT_FOLDER}"
)

# =====================================================
# SHOW SAMPLE
# =====================================================

print("\n" + "=" * 60)
print("FIRST 20 ROWS OF SORTED DATA")
print("=" * 60)

print(
    df_sorted[
        ["location_name", "date", "hour"]
    ].head(20)
)

# =====================================================
# SUMMARY
# =====================================================

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

print(f"Total rows           : {len(df_sorted):,}")
print(f"Total districts      : {df_sorted['location_name'].nunique()}")

if len(duplicates) > 0:
    print(f"Duplicate rows found : {len(duplicates):,}")
else:
    print("Duplicate rows found : 0")

print("\nDone.")