from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[3]
INPUT_FILE = (
    ROOT_DIR
    / "data"
    / "processed"
    / "pollution_index_scaled"
    / "pollution_index_scaled_ho_chi_minh_2025.csv"
)
OUTPUT_FILE = (
    ROOT_DIR
    / "src"
    / "EDA"
    / "pollution_index_scaled"
    / "eda_pollution_index_scaled_ho_chi_minh_summary.csv"
)


def main():
    df = pd.read_csv(INPUT_FILE, encoding="utf-8-sig")

    summary = df[["pollution_index_scaled"]].describe()
    summary.to_csv(OUTPUT_FILE, encoding="utf-8-sig")

    print(summary)
    print(f"\nSaved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
