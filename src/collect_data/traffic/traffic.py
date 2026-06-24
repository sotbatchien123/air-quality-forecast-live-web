"""Thu thap traffic lich su tu TomTom.

Muc luc:
1. Doc API key tu bien moi truong, khong hardcode secret.
2. Khai bao cac diem dai dien cua TP.HCM.
3. Goi TomTom theo tung gio va tinh congestion/traffic density.
4. Luu checkpoint CSV de tranh mat du lieu khi job dung giua chung.

Bien moi truong:
- `TOMTOM_API_KEYS`: nhieu key cach nhau bang dau phay, cham phay hoac xuong dong.
- `TOMTOM_API_KEY`: mot key duy nhat neu khong dung danh sach.
"""

import requests
import pandas as pd
import os
import threading

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# =====================
# CONFIG
# =====================

def load_api_keys():
    raw_keys = os.getenv("TOMTOM_API_KEYS") or os.getenv("TOMTOM_API_KEY", "")
    separators = [",", ";", "\n"]
    for separator in separators[1:]:
        raw_keys = raw_keys.replace(separator, separators[0])
    return [key.strip() for key in raw_keys.split(separators[0]) if key.strip()]


API_KEYS = load_api_keys()


OUTPUT_FILE = "data/raw/traffic/traffic_data2025_part3.csv"

MAX_WORKERS = 30
SAVE_EVERY = 50

# =====================
# KEY MANAGER
# =====================

active_keys = API_KEYS.copy()
key_lock = threading.Lock()

def get_next_key():

    global active_keys

    with key_lock:

        if len(active_keys) == 0:
            raise RuntimeError("NO_API_KEYS_LEFT")

        key = active_keys[0]

        active_keys.append(active_keys.pop(0))

        return key


def remove_key(bad_key):

    global active_keys

    with key_lock:

        if bad_key in active_keys:
            active_keys.remove(bad_key)

            print(
                f"\n[WARNING] Removed bad API key."
                f" Remaining keys: {len(active_keys)}"
            )

        if len(active_keys) == 0:
            raise RuntimeError("NO_API_KEYS_LEFT")


# =====================
# REPRESENTATIVE POINTS
# =====================

REPRESENTATIVE_POINTS = [

    ("Thu_Duc_City", 10.8231, 106.6297),

    ("District_1", 10.7756, 106.7009),
    ("District_3", 10.7842, 106.6840),
    ("District_4", 10.7570, 106.7015),
    ("District_5", 10.7540, 106.6638),
    ("District_6", 10.7481, 106.6350),
    ("District_7", 10.7290, 106.7215),
    ("District_8", 10.7240, 106.6285),
    ("District_10", 10.7737, 106.6670),
    ("District_11", 10.7630, 106.6437),
    ("District_12", 10.8678, 106.6415),

    ("Binh_Tan", 10.7653, 106.6037),
    ("Binh_Thanh", 10.8106, 106.7091),
    ("Go_Vap", 10.8387, 106.6653),
    ("Phu_Nhuan", 10.7991, 106.6797),
    ("Tan_Binh", 10.8015, 106.6520),
    ("Tan_Phu", 10.7901, 106.6286),

    ("Binh_Chanh", 10.6874, 106.5920),
    ("Cu_Chi", 11.0371, 106.5024),
    ("Hoc_Mon", 10.8894, 106.5923),
    ("Nha_Be", 10.6953, 106.7326),
]

# =====================
# SAVE FUNCTION
# =====================

def save_data(data):

    if len(data) == 0:
        return

    new_df = pd.DataFrame(data)

    if os.path.isfile(OUTPUT_FILE):

        old_df = pd.read_csv(OUTPUT_FILE)

        combined_df = pd.concat(
            [old_df, new_df],
            ignore_index=True
        )

        combined_df.drop_duplicates(
            subset=["date", "hour", "location_name"],
            inplace=True
        )

    else:
        combined_df = new_df

    combined_df.to_csv(
        OUTPUT_FILE,
        index=False,
        lineterminator="\n"
    )

# =====================
# API FUNCTION
# =====================

def get_historical_traffic(name, lat, lon, dt):

    api_key = get_next_key()

    timestamp = dt.strftime("%Y-%m-%dT%H:%M:%S")

    url = (
        "https://api.tomtom.com/traffic/services/4/flowSegmentData/"
        f"absolute/10/json?key={api_key}"
        f"&point={lat},{lon}"
        f"&date={timestamp}"
    )

    try:

        response = requests.get(
            url,
            timeout=15
        )

        # key chết
        if response.status_code in [401, 403]:

            remove_key(api_key)
            return None

        # rate limit
        if response.status_code == 429:

            print(
                f"Rate limit hit at {timestamp}"
            )
            return None

        if response.status_code != 200:

            return None

        data = response.json().get(
            "flowSegmentData"
        )

        if not data:
            return None

        current = data.get("currentSpeed")
        free = data.get("freeFlowSpeed")

        if (
            current is None
            or free is None
            or free == 0
        ):
            return None

        congestion_ratio = round(
            current / free,
            2
        )

        traffic_density = round(
            1 - congestion_ratio,
            2
        )

        return {
            "date": dt.strftime("%Y-%m-%d"),
            "hour": f"{dt.hour:02d}:00",
            "location_name": name,
            "lat": lat,
            "lon": lon,
            "currentSpeed": current,
            "freeFlowSpeed": free,
            "congestion_ratio": congestion_ratio,
            "traffic_density": traffic_density
        }

    except Exception:

        return None


# =====================
# MAIN
# =====================

def main():

    start_time = datetime(
        2025, 6, 5, 0, 0
    )

    end_time = datetime(
        2025, 7, 2, 23, 0
    )

    current_time = start_time

    all_data = []

    try:

        while current_time <= end_time:

            print(
                "Processing:",
                current_time.strftime(
                    "%Y-%m-%d %H:00"
                )
            )

            with ThreadPoolExecutor(
                max_workers=MAX_WORKERS
            ) as executor:

                futures = [

                    executor.submit(
                        get_historical_traffic,
                        name,
                        lat,
                        lon,
                        current_time
                    )

                    for (
                        name,
                        lat,
                        lon
                    ) in REPRESENTATIVE_POINTS
                ]

                # giữ nguyên thứ tự
                results = [
                    future.result()
                    for future in futures
                ]

                for result in results:

                    if result:

                        all_data.append(
                            result
                        )

                        if (
                            len(all_data)
                            % SAVE_EVERY
                            == 0
                        ):

                            save_data(
                                all_data
                            )

                            print(
                                f"Checkpoint:"
                                f" {len(all_data)} rows"
                            )

            current_time += timedelta(
                hours=1
            )

        print(
            "\nFinal saving..."
        )

        save_data(all_data)

        print(
            f"Finished. Total rows:"
            f" {len(all_data)}"
        )

    except RuntimeError as e:

        if str(e) == "NO_API_KEYS_LEFT":

            print(
                "\nAll API keys exhausted."
            )

            print(
                "Saving before exit..."
            )

            save_data(all_data)

            print(
                f"Saved {len(all_data)} rows."
            )

            return

        raise


if __name__ == "__main__":
    main()
