"""Build district-level GeoJSON for the static dashboard map.

Muc luc:
1. Tai GADM Vietnam level-2 GeoJSON.
2. Loc 5 tinh/thanh trong model va gan `location_key`.
3. Xu ly alias hanh chinh: Phu My, TP Thu Duc.
4. Don gian hoa toa do va ghi `web/data/model_regions.geojson`.

GADM dung ten khong co dau cach, vi du `HoChiMinh`. Script nay normalize ten
giong model de frontend join truc tiep GeoJSON voi prediction theo `location_key`.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_VNM_2.json"
DEFAULT_LOCATIONS_FILE = (
    ROOT_DIR
    / "data"
    / "raw"
    / "AQI"
    / "locations_5_provinces_old_boundaries.csv"
)
DEFAULT_OUTPUT = ROOT_DIR / "web" / "data" / "model_regions.geojson"

TARGET_PROVINCES = {
    "ba_ria_vung_tau",
    "dong_nai",
    "ho_chi_minh",
    "long_an",
    "tay_ninh",
}

DISTRICT_ALIASES = {
    ("ba_ria_vung_tau", "tan_thanh"): "phu_my",
    ("ho_chi_minh", "quan_2"): "thu_duc",
    ("ho_chi_minh", "quan_9"): "thu_duc",
}


def strip_accents(value: object) -> str:
    text = str(value).replace("\u0110", "D").replace("\u0111", "d")
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def district_key(value: object) -> str:
    text = strip_accents(value)
    text = re.sub(r"([a-z])([A-Z])", r"\1_\2", text)
    text = re.sub(r"([A-Za-z])(\d)", r"\1_\2", text)
    text = re.sub(r"(\d)([A-Za-z])", r"\1_\2", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    text = re.sub(r"^(thanh_pho|tp|tx|huyen|quan)_", "", text)
    if re.fullmatch(r"\d+", text):
        return f"quan_{text}"
    return text


def load_model_locations(path: Path) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            province_key = row["province_slug"]
            key = district_key(row["location_name"])
            location_key = f"{province_key}__{key}"
            output[location_key] = {
                "province_key": province_key,
                "district_key": key,
                "display_name": row["location_name"].replace("_", " "),
            }
    return output


def fetch_geojson(source_url: str) -> dict[str, Any]:
    with urllib.request.urlopen(source_url, timeout=90) as response:
        return json.load(response)


def perpendicular_distance(
    point: list[float],
    line_start: list[float],
    line_end: list[float],
) -> float:
    x, y = point[:2]
    x1, y1 = line_start[:2]
    x2, y2 = line_end[:2]
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / (dx * dx + dy * dy) ** 0.5


def rdp(points: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(points) <= 3:
        return points
    max_distance = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        distance = perpendicular_distance(points[i], points[0], points[-1])
        if distance > max_distance:
            index = i
            max_distance = distance
    if max_distance > tolerance:
        return rdp(points[: index + 1], tolerance)[:-1] + rdp(points[index:], tolerance)
    return [points[0], points[-1]]


def simplify_ring(ring: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(ring) <= 5:
        return [[round(point[0], 5), round(point[1], 5)] for point in ring]
    closed = ring[0] == ring[-1]
    working = ring[:-1] if closed else ring
    simplified = rdp(working, tolerance)
    if len(simplified) < 3:
        simplified = working[:3]
    simplified.append(simplified[0])
    return [[round(point[0], 5), round(point[1], 5)] for point in simplified]


def simplify_geometry(geometry: dict[str, Any], tolerance: float) -> dict[str, Any]:
    if geometry["type"] == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [
                simplify_ring(ring, tolerance) for ring in geometry["coordinates"]
            ],
        }
    if geometry["type"] == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [simplify_ring(ring, tolerance) for ring in polygon]
                for polygon in geometry["coordinates"]
            ],
        }
    raise ValueError(f"Unsupported geometry type: {geometry['type']}")


def region_feature(
    feature: dict[str, Any],
    model_locations: dict[str, dict[str, str]],
    tolerance: float,
) -> dict[str, Any] | None:
    properties = feature["properties"]
    province_key = district_key(properties["NAME_1"])
    if province_key not in TARGET_PROVINCES:
        return None

    gadm_district_key = district_key(properties["NAME_2"])
    model_district_key = DISTRICT_ALIASES.get(
        (province_key, gadm_district_key),
        gadm_district_key,
    )
    location_key = f"{province_key}__{model_district_key}"
    if location_key not in model_locations:
        return None

    model = model_locations[location_key]
    return {
        "type": "Feature",
        "properties": {
            "location_key": location_key,
            "province_key": province_key,
            "district_key": model["district_key"],
            "display_name": model["display_name"],
            "gadm_name_1": properties["NAME_1"],
            "gadm_name_2": properties["NAME_2"],
            "gadm_type_2": properties["TYPE_2"],
            "source": "GADM 4.1 level 2",
        },
        "geometry": simplify_geometry(feature["geometry"], tolerance),
    }


def build_geojson(
    source_url: str,
    locations_file: Path,
    output_file: Path,
    tolerance: float,
) -> Path:
    model_locations = load_model_locations(locations_file)
    source = fetch_geojson(source_url)
    features = [
        region_feature(feature, model_locations, tolerance)
        for feature in source["features"]
    ]
    features = [feature for feature in features if feature is not None]
    payload = {
        "type": "FeatureCollection",
        "name": "dap391_model_regions",
        "metadata": {
            "source": "GADM 4.1 Vietnam level 2",
            "source_url": source_url,
            "note": (
                "District boundaries are normalized to model location_key. "
                "Some administrative changes are represented by aliases."
            ),
            "feature_count": len(features),
        },
        "features": features,
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    covered_keys = {feature["properties"]["location_key"] for feature in features}
    missing = sorted(set(model_locations) - covered_keys)
    print(f"Wrote {len(features)} GeoJSON features -> {output_file}")
    print(f"Covered model locations: {len(covered_keys)}/{len(model_locations)}")
    if missing:
        print("No polygon found for:")
        for key in missing:
            print(f"- {key}")
    return output_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build dashboard region GeoJSON")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--locations-file", type=Path, default=DEFAULT_LOCATIONS_FILE)
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tolerance", type=float, default=0.0015)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_geojson(
        args.source_url,
        args.locations_file.resolve(),
        args.output_file.resolve(),
        args.tolerance,
    )


if __name__ == "__main__":
    main()
