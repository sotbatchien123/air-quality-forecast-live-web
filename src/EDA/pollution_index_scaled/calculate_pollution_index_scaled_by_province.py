from pathlib import Path
import re
import unicodedata

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[3]

TRAFFIC_DIR = ROOT_DIR / "data" / "raw" / "traffic"
POPULATION_FILE = ROOT_DIR / "data" / "raw" / "population" / "population_southeast_2025.csv"
TREE_FILE = ROOT_DIR / "data" / "raw" / "tree" / "synthetic_tree_green_data_southeast_2025.csv"
WEATHER_FILE = ROOT_DIR / "data" / "raw" / "weather" / "hcm_weather_2025.csv"
VEHICLE_FILE = TRAFFIC_DIR / "VehicleCount.csv"
OUTPUT_DIR = ROOT_DIR / "data" / "processed" / "pollution_index_scaled"


# Constants copied from pollution_index_scaled_for_merge.py.
TREE_ABSORPTION = 2.6
EMISSION_PER_PERSON = 0.44
EMISSION_FACTOR = 192


PROVINCES = [
    {
        "province": "Bà Rịa - Vũng Tàu",
        "traffic_file": "traffic_ba_ria_vung_tau_2025.csv",
        "output_file": "pollution_index_scaled_ba_ria_vung_tau_2025.csv",
    },
    {
        "province": "Đồng Nai",
        "traffic_file": "traffic_dong_nai_2025.csv",
        "output_file": "pollution_index_scaled_dong_nai_2025.csv",
    },
    {
        "province": "TP Hồ Chí Minh",
        "traffic_file": "traffic_ho_chi_minh_2025.csv",
        "output_file": "pollution_index_scaled_ho_chi_minh_2025.csv",
    },
    {
        "province": "Long An",
        "traffic_file": "traffic_long_an_2025.csv",
        "output_file": "pollution_index_scaled_long_an_2025.csv",
    },
    {
        "province": "Tây Ninh",
        "traffic_file": "traffic_tay_ninh_2025.csv",
        "output_file": "pollution_index_scaled_tay_ninh_2025.csv",
    },
]


PROVINCE_ALIASES = {
    "Ba_Ria_Vung_Tau": "Bà Rịa - Vũng Tàu",
    "Dong_Nai": "Đồng Nai",
    "Ho_Chi_Minh": "TP Hồ Chí Minh",
    "HCM": "TP Hồ Chí Minh",
    "Long_An": "Long An",
    "Tay_Ninh": "Tây Ninh",
}


def strip_accents(value):
    value = str(value).replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def district_key(value):
    text = re.sub(r"\s+", " ", str(value).strip())
    text = strip_accents(text).lower()

    if not re.fullmatch(r"quan\s+\d+", text):
        text = re.sub(r"^(tp|tx|huyen|quan)\s+", "", text)

    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_(tn|dn|la)$", "", text)
    return text


def normalize_province(value):
    value = str(value).strip()
    return PROVINCE_ALIASES.get(value, value)


def min_max_normalize(series):
    value_range = series.max() - series.min()
    if pd.isna(value_range) or value_range == 0:
        return pd.Series(0, index=series.index, dtype="float64")
    return (series - series.min()) / value_range


def require_columns(df, columns, file_path):
    missing = [column for column in columns if column not in df.columns]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Missing columns in {file_path}: {missing_text}")


def require_no_missing(df, column, province, source_name):
    missing = df.loc[df[column].isna(), "location_name"].drop_duplicates().tolist()
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"{province}: missing {source_name} data for {missing_text}")


def load_population():
    population = pd.read_csv(POPULATION_FILE, encoding="utf-8-sig")
    require_columns(
        population,
        [
            "District",
            "Province_City",
            "Type",
            "Area_km2",
            "Population",
            "Density_person_km2",
        ],
        POPULATION_FILE,
    )

    population = population.rename(
        columns={
            "District": "district",
            "Province_City": "province",
            "Type": "type",
            "Area_km2": "area_km2",
            "Population": "population",
            "Density_person_km2": "density_person_km2",
        }
    )
    population["province"] = population["province"].apply(normalize_province)
    population["district_key"] = population["district"].apply(district_key)

    return population[
        [
            "province",
            "district_key",
            "district",
            "type",
            "area_km2",
            "population",
            "density_person_km2",
        ]
    ]


def load_tree_data():
    tree = pd.read_csv(TREE_FILE, encoding="utf-8-sig")
    require_columns(
        tree,
        [
            "province",
            "district",
            "green_area_m2",
            "green_per_capita_m2",
        ],
        TREE_FILE,
    )

    tree["province"] = tree["province"].apply(normalize_province)
    tree["district_key"] = tree["district"].apply(district_key)

    return tree[
        [
            "province",
            "district_key",
            "green_area_m2",
            "green_per_capita_m2",
        ]
    ]


def load_vehicle_counts():
    vehicles = pd.read_csv(VEHICLE_FILE)
    require_columns(vehicles, ["location_name", "Province", "Total_Vehicles"], VEHICLE_FILE)

    vehicles = vehicles.rename(columns={"Province": "province"})
    vehicles["province"] = vehicles["province"].apply(normalize_province)
    vehicles["district_key"] = vehicles["location_name"].apply(district_key)
    vehicles["estimated_vehicles"] = vehicles["Total_Vehicles"]

    return vehicles[["province", "district_key", "estimated_vehicles"]]


def load_weather():
    weather = pd.read_csv(WEATHER_FILE)
    require_columns(
        weather,
        [
            "date",
            "hour",
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
            "cloud_cover",
        ],
        WEATHER_FILE,
    )

    return weather[
        [
            "date",
            "hour",
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
            "cloud_cover",
        ]
    ]


def apply_pollution_index_formula(df):
    df["emission_vehicle"] = (
        df["estimated_vehicles"] * df["currentspeed"] * EMISSION_FACTOR
    )

    df["emission_population"] = df["population"] * EMISSION_PER_PERSON

    df["emission_sum_grams"] = df["emission_vehicle"] + df["emission_population"]

    df["trees"] = df["green_area_m2"] / 25
    df["absorption"] = TREE_ABSORPTION * df["trees"]
    df["ERI"] = df["absorption"] / df["emission_sum_grams"]
    df["ERI"] = df["ERI"].clip(0, 1)

    wind_norm = min_max_normalize(df["wind_speed_10m"])
    rain_norm = min_max_normalize(df["precipitation"])
    humidity_norm = min_max_normalize(df["relative_humidity_2m"])
    temp_norm = min_max_normalize(df["temperature_2m"])

    df["WDI"] = (wind_norm + rain_norm) / (humidity_norm + temp_norm)
    df["WDI"] = df["WDI"].replace([np.inf, -np.inf], np.nan)

    wdi_min = df["WDI"].min()
    wdi_max = df["WDI"].max()
    if pd.isna(wdi_min) or pd.isna(wdi_max) or wdi_max == wdi_min:
        df["WDI_norm"] = 0
    else:
        df["WDI_norm"] = (df["WDI"] - wdi_min) / (wdi_max - wdi_min)
    df["WDI_norm"] = df["WDI_norm"].round(2)

    df["pollution_index"] = (
        df["emission_sum_grams"] * (1 - df["ERI"]) * (1 - df["WDI_norm"])
    )

    pi_min = df["pollution_index"].min()
    pi_max = df["pollution_index"].max()
    if pd.isna(pi_min) or pd.isna(pi_max) or pi_max == pi_min:
        df["pollution_index_scaled"] = 0
    else:
        df["pollution_index_scaled"] = 100 * (
            (df["pollution_index"] - pi_min) / (pi_max - pi_min)
        )

    df["pollution_index"] = df["pollution_index"].round().astype("int64")
    df["pollution_index_scaled"] = df["pollution_index_scaled"].round().astype("int64")

    return df


def build_province_dataset(province_config, population, tree, vehicles, weather):
    province = province_config["province"]
    traffic_file = TRAFFIC_DIR / province_config["traffic_file"]

    traffic = pd.read_csv(traffic_file)
    require_columns(
        traffic,
        [
            "date",
            "hour",
            "location_name",
            "lat",
            "lon",
            "currentSpeed",
            "freeFlowSpeed",
            "congestion_ratio",
            "traffic_density",
        ],
        traffic_file,
    )

    traffic["province"] = province
    traffic["district_key"] = traffic["location_name"].apply(district_key)

    province_population = population[population["province"] == province]
    province_tree = tree[tree["province"] == province]
    province_vehicles = vehicles[vehicles["province"] == province]

    df = traffic.merge(
        province_vehicles,
        on=["province", "district_key"],
        how="left",
        validate="many_to_one",
    )
    require_no_missing(df, "estimated_vehicles", province, "vehicle count")

    df = df.merge(
        province_population,
        on=["province", "district_key"],
        how="left",
        validate="many_to_one",
    )
    require_no_missing(df, "population", province, "population")

    df = df.merge(
        province_tree,
        on=["province", "district_key"],
        how="left",
        validate="many_to_one",
    )
    require_no_missing(df, "green_area_m2", province, "tree/green area")

    df = df.merge(weather, on=["date", "hour"], how="left", validate="many_to_one")
    require_no_missing(df, "temperature_2m", province, "weather")

    df = df.rename(
        columns={
            "currentSpeed": "currentspeed",
            "freeFlowSpeed": "freeflowspeed",
        }
    )

    return apply_pollution_index_formula(df)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    population = load_population()
    tree = load_tree_data()
    vehicles = load_vehicle_counts()
    weather = load_weather()

    for province_config in PROVINCES:
        province = province_config["province"]
        result = build_province_dataset(
            province_config,
            population=population,
            tree=tree,
            vehicles=vehicles,
            weather=weather,
        )

        output_file = OUTPUT_DIR / province_config["output_file"]
        result.to_csv(output_file, index=False, encoding="utf-8-sig")

        print(
            f"Saved {output_file.name}: "
            f"{output_file.relative_to(ROOT_DIR)} ({len(result):,} rows)"
        )


if __name__ == "__main__":
    main()
