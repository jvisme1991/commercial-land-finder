from datetime import datetime
from pathlib import Path
import re

import geopandas as gpd
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]

PARCELS_PATH = BASE_DIR / "data" / "parcels" / "target parcels.shp"
ROADS_PATH = BASE_DIR / "data" / "roads" / "Road_Centerline.shp"
CITY_LIMITS_PATH = BASE_DIR / "data" / "city_limits" / "City_Limits.shp"
OWNERSHIP_DIR = BASE_DIR / "data" / "ownership"
MANUAL_ENRICHMENT_PATH = OWNERSHIP_DIR / "manual_enrichment.csv"
OUTPUT_PATH = BASE_DIR / "outputs" / "land_search_results.csv"

MIN_ACRES = 0.5
MAX_ACRES = 10
BUFFER_FEET = 500
LOW_IMPROVEMENT_RATIO = 0.25
HIGH_LAND_VALUE_RATIO = 0.70
CAD_SEARCH_URL = "https://smithcad-search.gsacorp.io/"

TARGET_ROADS = [
    "31",
    "64",
    "155",
    "323",
    "Old Jacksonville",
    "Troup",
    "Gentry",
    "Paluxy",
    "Broadway",
]


OWNERSHIP_OUTPUT_COLUMNS = [
    "owner_name",
    "mailing_address",
    "mailing_city",
    "appraised_value",
    "land_value",
    "improvement_value",
    "notes",
]

OWNERSHIP_COLUMN_CANDIDATES = {
    "ACCOUNT": ["ACCOUNT", "Account", "Account Number", "Acct", "AcctNum"],
    "PARCELID": ["PARCELID", "Parcel ID", "ParcelID", "Parcel Id", "PID"],
    "owner_name": [
        "owner_name",
        "Owner Name",
        "Owner",
        "OWNER",
        "OWNER_NAME",
        "Name",
    ],
    "mailing_address": [
        "mailing_address",
        "Mailing Address",
        "Mail Address",
        "MAIL_ADDR",
        "Mailing Addr",
        "Owner Address",
    ],
    "mailing_city": [
        "mailing_city",
        "Mailing City",
        "Mail City",
        "MAIL_CITY",
        "Owner City",
    ],
    "appraised_value": [
        "appraised_value",
        "Appraised Value",
        "Total Appraised Value",
        "Market Value",
        "Total Value",
        "APPRAISED",
        "APPRAISED_VALUE",
    ],
    "land_value": [
        "land_value",
        "Land Value",
        "LAND_VALUE",
        "Land Market Value",
        "LAND",
    ],
    "improvement_value": [
        "improvement_value",
        "Improvement Value",
        "Improvements Value",
        "IMPROVEMENT_VALUE",
        "Improvement",
        "IMPROVEMENTS",
        "Improvement Market Value",
    ],
    "notes": ["notes", "Notes", "NOTES"],
}


def normalize_column_name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def find_column(columns, candidates):
    normalized_columns = {
        normalize_column_name(column): column for column in columns
    }
    for candidate in candidates:
        match = normalized_columns.get(normalize_column_name(candidate))
        if match:
            return match
    return None


def clean_join_key(series):
    return series.fillna("").astype(str).str.strip()


def clean_money(series):
    cleaned = (
        series.fillna("")
        .astype(str)
        .str.replace(r"[$,]", "", regex=True)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def has_filter_value(value):
    return value is not None and pd.notna(value)


def apply_numeric_range_filter(data, column, min_value=None, max_value=None):
    has_min = has_filter_value(min_value)
    has_max = has_filter_value(max_value)

    if not has_min and not has_max:
        return data

    if column not in data.columns or data[column].notna().sum() == 0:
        return data

    filtered = data[data[column].notna()].copy()

    if has_min:
        filtered = filtered[filtered[column].ge(min_value)].copy()

    if has_max:
        filtered = filtered[filtered[column].le(max_value)].copy()

    return filtered


def load_layers():
    parcels = gpd.read_file(PARCELS_PATH)
    roads = gpd.read_file(ROADS_PATH)
    city_limits = gpd.read_file(CITY_LIMITS_PATH)
    return parcels, roads, city_limits


def load_ownership_data():
    csv_paths = sorted(OWNERSHIP_DIR.glob("*.csv"))
    output_columns = ["ACCOUNT", "PARCELID"] + OWNERSHIP_OUTPUT_COLUMNS

    if not csv_paths:
        return pd.DataFrame(columns=output_columns)

    ownership_frames = []
    for csv_path in csv_paths:
        ownership_frames.append(pd.read_csv(csv_path, dtype=str))

    ownership = pd.concat(ownership_frames, ignore_index=True)
    normalized = pd.DataFrame(index=ownership.index)

    for output_column in output_columns:
        source_column = find_column(
            ownership.columns,
            OWNERSHIP_COLUMN_CANDIDATES[output_column],
        )
        if source_column:
            normalized[output_column] = ownership[source_column]
        else:
            normalized[output_column] = pd.NA

    normalized["ACCOUNT"] = clean_join_key(normalized["ACCOUNT"])
    normalized["PARCELID"] = clean_join_key(normalized["PARCELID"])

    for value_column in ["appraised_value", "land_value", "improvement_value"]:
        normalized[value_column] = clean_money(normalized[value_column])

    normalized = normalized[
        (normalized["ACCOUNT"] != "") | (normalized["PARCELID"] != "")
    ].copy()

    return normalized


def add_ownership_data(parcels):
    ownership = load_ownership_data()

    for output_column in OWNERSHIP_OUTPUT_COLUMNS:
        parcels[output_column] = pd.NA

    if not ownership.empty:
        parcels["_ACCOUNT_JOIN"] = clean_join_key(parcels["ACCOUNT"])
        parcels["_PARCELID_JOIN"] = clean_join_key(parcels["PARCELID"])

        account_ownership = ownership[
            ownership["ACCOUNT"].fillna("").astype(str).str.strip() != ""
        ].copy()
        parcel_ownership = ownership[
            ownership["PARCELID"].fillna("").astype(str).str.strip() != ""
        ].copy()

        if not account_ownership.empty:
            account_ownership = account_ownership.drop_duplicates(
                subset=["ACCOUNT"], keep="first"
            )
            account_ownership = account_ownership.set_index("ACCOUNT")
            for output_column in OWNERSHIP_OUTPUT_COLUMNS:
                parcels[output_column] = parcels["_ACCOUNT_JOIN"].map(
                    account_ownership[output_column]
                )

        if not parcel_ownership.empty:
            parcel_ownership = parcel_ownership.drop_duplicates(
                subset=["PARCELID"], keep="first"
            )
            parcel_ownership = parcel_ownership.set_index("PARCELID")
            for output_column in OWNERSHIP_OUTPUT_COLUMNS:
                parcel_matches = parcels["_PARCELID_JOIN"].map(
                    parcel_ownership[output_column]
                )
                parcels[output_column] = parcels[output_column].combine_first(
                    parcel_matches
                )

        parcels = parcels.drop(columns=["_ACCOUNT_JOIN", "_PARCELID_JOIN"])

    parcels["appraised_value"] = pd.to_numeric(
        parcels["appraised_value"], errors="coerce"
    )
    parcels["land_value"] = pd.to_numeric(parcels["land_value"], errors="coerce")
    parcels["improvement_value"] = pd.to_numeric(
        parcels["improvement_value"], errors="coerce"
    )

    parcel_city = parcels["POSTAL_CIT"].fillna("").astype(str).str.strip().str.casefold()
    mailing_city = (
        parcels["mailing_city"].fillna("").astype(str).str.strip().str.casefold()
    )
    parcels["absentee_owner"] = (mailing_city != "") & (parcel_city != mailing_city)
    total_value = parcels["appraised_value"].where(parcels["appraised_value"] != 0)
    parcels["improvement_ratio"] = parcels["improvement_value"] / total_value
    parcels["land_to_total_value_ratio"] = parcels["land_value"] / total_value
    parcels["cad_lookup_link"] = CAD_SEARCH_URL

    return parcels


def run_search(
    min_acres=MIN_ACRES,
    max_acres=MAX_ACRES,
    target_roads=None,
    buffer_feet=BUFFER_FEET,
    commercial_only=False,
    inside_city_limits_only=False,
    city_status="Any",
    absentee_owners_only=False,
    min_appraised_value=None,
    max_appraised_value=None,
    min_improvement_ratio=None,
    max_improvement_ratio=None,
    min_land_value_ratio=None,
    max_land_value_ratio=None,
    output_path=None,
):
    target_roads = target_roads or TARGET_ROADS

    parcels, roads, city_limits = load_layers()

    parcels = parcels[
        (parcels["CALC_ACRE"] >= min_acres)
        & (parcels["CALC_ACRE"] <= max_acres)
    ].copy()

    if commercial_only:
        parcels = parcels[
            parcels["Type"].fillna("").str.contains("Commercial", case=False)
        ].copy()

    road_pattern = "|".join(re.escape(road) for road in target_roads if road.strip())
    if not road_pattern:
        raise ValueError("Enter at least one target road name.")

    target_roads = roads[
        roads["FullName"].fillna("").str.contains(
            road_pattern,
            case=False,
            regex=True,
        )
    ].copy()

    if target_roads.empty:
        raise ValueError("No matching target roads were found.")

    target_crs = "EPSG:2276"

    parcels = parcels.to_crs(target_crs)
    target_roads = target_roads.to_crs(target_crs)
    city_limits = city_limits.to_crs(target_crs)

    road_buffer = target_roads.geometry.buffer(buffer_feet).union_all()

    parcels_near_roads = parcels[parcels.intersects(road_buffer)].copy()

    city_union = city_limits.geometry.union_all()
    parcels_near_roads["inside_city_limits"] = parcels_near_roads.intersects(city_union)

    if inside_city_limits_only or city_status == "Inside City Limits":
        parcels_near_roads = parcels_near_roads[
            parcels_near_roads["inside_city_limits"] == True
        ].copy()
    elif city_status == "Outside City Limits":
        parcels_near_roads = parcels_near_roads[
            parcels_near_roads["inside_city_limits"] == False
        ].copy()

    parcels_near_roads = add_ownership_data(parcels_near_roads)

    if absentee_owners_only:
        parcels_near_roads = parcels_near_roads[
            parcels_near_roads["absentee_owner"] == True
        ].copy()

    parcels_near_roads = apply_numeric_range_filter(
        parcels_near_roads,
        "appraised_value",
        min_appraised_value,
        max_appraised_value,
    )
    parcels_near_roads = apply_numeric_range_filter(
        parcels_near_roads,
        "improvement_ratio",
        min_improvement_ratio,
        max_improvement_ratio,
    )
    parcels_near_roads = apply_numeric_range_filter(
        parcels_near_roads,
        "land_to_total_value_ratio",
        min_land_value_ratio,
        max_land_value_ratio,
    )

    parcels_near_roads["score"] = 0

    parcels_near_roads.loc[
        parcels_near_roads["CALC_ACRE"].between(1, 5), "score"
    ] += 20

    parcels_near_roads.loc[
        parcels_near_roads["Type"].fillna("").str.contains("Commercial", case=False),
        "score",
    ] += 20

    parcels_near_roads.loc[
        parcels_near_roads["inside_city_limits"] == True,
        "score",
    ] += 10

    parcels_near_roads.loc[
        parcels_near_roads["absentee_owner"] == True,
        "score",
    ] += 10

    low_improvement_ratio = max_improvement_ratio or LOW_IMPROVEMENT_RATIO
    high_land_value_ratio = min_land_value_ratio or HIGH_LAND_VALUE_RATIO

    parcels_near_roads.loc[
        parcels_near_roads["improvement_ratio"].le(low_improvement_ratio),
        "score",
    ] += 15

    parcels_near_roads.loc[
        parcels_near_roads["land_to_total_value_ratio"].gt(high_land_value_ratio),
        "score",
    ] += 15

    output_columns = [
        "ACCOUNT",
        "cad_lookup_link",
        "PARCELID",
        "PIN",
        "FULLNAME",
        "ADDRESS",
        "CITY_COUNT",
        "POSTAL_CIT",
        "ZIPCODE",
        "CALC_ACRE",
        "Type",
        "owner_name",
        "mailing_address",
        "mailing_city",
        "appraised_value",
        "land_value",
        "improvement_value",
        "notes",
        "absentee_owner",
        "improvement_ratio",
        "land_to_total_value_ratio",
        "inside_city_limits",
        "score",
    ]

    results = parcels_near_roads[output_columns + ["geometry"]].sort_values(
        by="score",
        ascending=False,
    )

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = BASE_DIR / "outputs" / f"land_search_results_{timestamp}.csv"

    output_path = Path(output_path)
    output_path.parent.mkdir(exist_ok=True)
    results.drop(columns=["geometry"]).to_csv(output_path, index=False)

    return results, output_path


def main():
    print("Running commercial land search...")

    results, output_path = run_search(output_path=OUTPUT_PATH)

    print(f"Done. Exported {len(results)} results to:")
    print(output_path)


if __name__ == "__main__":
    main()
