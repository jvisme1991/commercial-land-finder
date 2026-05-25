from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from scripts.run_search import (
    BUFFER_FEET,
    MANUAL_ENRICHMENT_PATH,
    MAX_ACRES,
    MIN_ACRES,
    ROADS_PATH,
    run_search,
)


st.set_page_config(page_title="Commercial Land Finder", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
CAD_LINK_LABEL = "Open Smith CAD search"
MANUAL_ENRICHMENT_COLUMNS = [
    "ACCOUNT",
    "PARCELID",
    "ADDRESS",
    "POSTAL_CIT",
    "cad_lookup_link",
    "owner_name",
    "mailing_address",
    "mailing_city",
    "appraised_value",
    "land_value",
    "improvement_value",
    "notes",
]

COMMON_TARGET_ROADS = [
    "US Highway 69",
    "State Highway 31",
    "State Highway 64",
    "State Highway 155",
    "Loop 323",
    "Old Jacksonville Highway",
    "Troup Highway",
    "Gentry Parkway",
    "Paluxy Drive",
    "Broadway Avenue",
]

DEFAULT_ROAD_SEARCH_TERMS = [
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

COMMON_TARGET_FALLBACK_TERMS = {
    "US Highway 69": [["Hwy", "69"], ["Highway", "69"]],
    "State Highway 31": [["Hwy", "31"], ["Highway", "31"]],
    "State Highway 64": [["Hwy", "64"], ["Highway", "64"]],
    "State Highway 155": [["Hwy", "155"], ["Highway", "155"]],
    "Loop 323": [["Loop", "323"]],
    "Old Jacksonville Highway": [["Old Jacksonville"]],
    "Troup Highway": [["Troup"]],
    "Gentry Parkway": [["Gentry"]],
    "Paluxy Drive": [["Paluxy"]],
    "Broadway Avenue": [["Broadway"]],
}


def parse_road_names(value):
    road_names = []
    for line in value.splitlines():
        for item in line.split(","):
            road_name = item.strip()
            if road_name:
                road_names.append(road_name)
    return road_names


def parse_optional_limit(value, *, scale=1.0, zero_is_none=True, max_no_limit=None):
    cleaned = str(value).replace(",", "").strip()
    if cleaned == "":
        return None

    parsed = float(cleaned)
    if parsed < 0:
        raise ValueError("Filter values must be zero or greater.")
    if zero_is_none and parsed == 0:
        return None
    if max_no_limit is not None and parsed >= max_no_limit:
        return None
    return parsed / scale


def validate_optional_range(label, min_value, max_value):
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValueError(f"{label} minimum must be less than or equal to maximum.")


@st.cache_data(show_spinner=False)
def load_road_names():
    roads = gpd.read_file(ROADS_PATH)
    road_names = roads["FullName"].fillna("").astype(str).str.strip()
    road_names = road_names[road_names != ""].drop_duplicates()
    return sorted(road_names.tolist(), key=str.casefold)


def get_default_road_names(road_names):
    selected = []
    selected_lookup = set()
    lower_name_lookup = {name.casefold(): name for name in road_names}

    for road_name in COMMON_TARGET_ROADS:
        exact_match = lower_name_lookup.get(road_name.casefold())
        if exact_match and exact_match not in selected_lookup:
            selected.append(exact_match)
            selected_lookup.add(exact_match)
            continue

        for term_group in COMMON_TARGET_FALLBACK_TERMS[road_name]:
            for available_road_name in road_names:
                if all(
                    term.casefold() in available_road_name.casefold()
                    for term in term_group
                ) and available_road_name not in selected_lookup:
                    selected.append(available_road_name)
                    selected_lookup.add(available_road_name)

    for search_term in DEFAULT_ROAD_SEARCH_TERMS:
        search_term = search_term.casefold()
        for road_name in road_names:
            lower_road_name = road_name.casefold()
            is_number_search = search_term.isnumeric()
            is_likely_highway = "hwy" in lower_road_name or "loop" in lower_road_name

            if (
                search_term in lower_road_name
                and road_name not in selected_lookup
                and (not is_number_search or is_likely_highway)
            ):
                selected.append(road_name)
                selected_lookup.add(road_name)

    return selected


def results_for_csv(results):
    if "geometry" in results.columns:
        return results.drop(columns=["geometry"])
    return results


def get_parcel_key_frame(data):
    key_frame = data.copy()
    key_frame["parcel_key"] = (
        key_frame["ACCOUNT"].fillna(key_frame["PARCELID"]).fillna("").astype(str)
    )
    return key_frame


def load_manual_enrichment():
    if not MANUAL_ENRICHMENT_PATH.exists():
        return pd.DataFrame(columns=MANUAL_ENRICHMENT_COLUMNS)
    return pd.read_csv(MANUAL_ENRICHMENT_PATH, dtype=str)


def save_manual_enrichment(enrichment_data):
    MANUAL_ENRICHMENT_PATH.parent.mkdir(exist_ok=True)

    existing = load_manual_enrichment()
    cleaned = enrichment_data.copy()

    for column in MANUAL_ENRICHMENT_COLUMNS:
        if column not in existing.columns:
            existing[column] = pd.NA
        if column not in cleaned.columns:
            cleaned[column] = pd.NA

    existing = existing[MANUAL_ENRICHMENT_COLUMNS]
    cleaned = cleaned[MANUAL_ENRICHMENT_COLUMNS]

    existing["ACCOUNT"] = existing["ACCOUNT"].fillna("").astype(str).str.strip()
    cleaned["ACCOUNT"] = cleaned["ACCOUNT"].fillna("").astype(str).str.strip()
    cleaned = cleaned[cleaned["ACCOUNT"] != ""].copy()

    merged = pd.concat(
        [
            existing[~existing["ACCOUNT"].isin(cleaned["ACCOUNT"])],
            cleaned,
        ],
        ignore_index=True,
    )
    merged.to_csv(MANUAL_ENRICHMENT_PATH, index=False)


def format_popup_value(value):
    if value is None or str(value) == "nan":
        return ""
    return value


def make_parcel_map(results, selected_parcel_ids):
    map_results = results.to_crs(epsg=4326).copy()
    center = map_results.geometry.union_all().centroid
    parcel_map = folium.Map(location=[center.y, center.x], zoom_start=12)

    selected_lookup = set(selected_parcel_ids)
    map_results["parcel_map_id"] = (
        map_results["ACCOUNT"].fillna(map_results["PARCELID"]).fillna("").astype(str)
    )
    map_results["selected"] = map_results["parcel_map_id"].isin(selected_lookup)
    map_results["popup_acreage"] = map_results["CALC_ACRE"].round(2)

    def style_parcel(feature):
        is_selected = feature["properties"].get("selected", False)
        return {
            "color": "#d62728" if is_selected else "#2563eb",
            "weight": 4 if is_selected else 1,
            "fillColor": "#facc15" if is_selected else "#60a5fa",
            "fillOpacity": 0.45 if is_selected else 0.2,
        }

    folium.GeoJson(
        map_results,
        style_function=style_parcel,
        popup=folium.GeoJsonPopup(
            fields=["popup_acreage", "ADDRESS", "PARCELID", "score"],
            aliases=["Acreage", "Address", "Parcel ID", "Score"],
            localize=True,
            max_width=320,
        ),
        tooltip=folium.GeoJsonTooltip(
            fields=["PARCELID", "score"],
            aliases=["Parcel ID", "Score"],
            localize=True,
        ),
    ).add_to(parcel_map)

    bounds = map_results.total_bounds
    parcel_map.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    return parcel_map


st.title("Commercial Land Finder")

road_names = load_road_names()
default_road_names = get_default_road_names(road_names)

with st.form("search_form"):
    col1, col2 = st.columns(2)

    with col1:
        min_acres = st.number_input(
            "Minimum acres",
            min_value=0.0,
            value=float(MIN_ACRES),
            step=0.25,
        )
        max_acres = st.number_input(
            "Maximum acres",
            min_value=0.0,
            value=float(MAX_ACRES),
            step=0.25,
        )
        buffer_feet = st.number_input(
            "Road buffer distance (feet)",
            min_value=0,
            value=int(BUFFER_FEET),
            step=50,
        )
        absentee_owners_only = st.checkbox("Absentee owners only")
        st.markdown("Appraised value range")
        value_col1, value_col2 = st.columns(2)
        with value_col1:
            min_appraised_value_text = st.text_input(
                "Minimum appraised value",
                value="0",
                help="Use 0 or blank for no minimum.",
            )
        with value_col2:
            max_appraised_value_text = st.text_input(
                "Maximum appraised value",
                value="0",
                help="Use 0 or blank for no maximum.",
            )

    with col2:
        selected_road_names = st.multiselect(
            "Target road names",
            options=road_names,
            default=default_road_names,
            placeholder="Search and select roads",
        )
        additional_road_terms_text = st.text_area(
            "Additional road name search terms",
            help="Optional. Add one road name or search term per line, or separate with commas.",
            height=100,
        )
        commercial_only = st.checkbox("Commercial only")
        city_status = st.selectbox(
            "City status",
            options=["Any", "Inside City Limits", "Outside City Limits"],
        )
        st.markdown("Improvement ratio range (%)")
        improvement_col1, improvement_col2 = st.columns(2)
        with improvement_col1:
            min_improvement_ratio_text = st.text_input(
                "Minimum improvement ratio",
                value="0",
                help="Use 0 or blank for no minimum.",
            )
        with improvement_col2:
            max_improvement_ratio_text = st.text_input(
                "Maximum improvement ratio",
                value="100",
                help="Use 0, blank, or 100 for no maximum.",
            )

        st.markdown("Land percentage range (%)")
        land_col1, land_col2 = st.columns(2)
        with land_col1:
            min_land_percentage_text = st.text_input(
                "Minimum land percentage",
                value="0",
                help="Use 0 or blank for no minimum.",
            )
        with land_col2:
            max_land_percentage_text = st.text_input(
                "Maximum land percentage",
                value="100",
                help="Use 0, blank, or 100 for no maximum.",
            )

    submitted = st.form_submit_button("Run search")

if submitted:
    if max_acres < min_acres:
        st.error("Maximum acres must be greater than or equal to minimum acres.")
    else:
        additional_road_terms = parse_road_names(additional_road_terms_text)
        target_roads = selected_road_names + additional_road_terms

        if not target_roads:
            st.error("Select at least one road or enter an additional road name search term.")
        else:
            try:
                with st.spinner("Running GIS search..."):
                    min_appraised_value_filter = parse_optional_limit(
                        min_appraised_value_text
                    )
                    max_appraised_value_filter = parse_optional_limit(
                        max_appraised_value_text
                    )
                    min_improvement_ratio_filter = parse_optional_limit(
                        min_improvement_ratio_text,
                        scale=100,
                    )
                    max_improvement_ratio_filter = parse_optional_limit(
                        max_improvement_ratio_text,
                        scale=100,
                        max_no_limit=100,
                    )
                    min_land_value_ratio_filter = parse_optional_limit(
                        min_land_percentage_text,
                        scale=100,
                    )
                    max_land_value_ratio_filter = parse_optional_limit(
                        max_land_percentage_text,
                        scale=100,
                        max_no_limit=100,
                    )
                    validate_optional_range(
                        "Appraised value",
                        min_appraised_value_filter,
                        max_appraised_value_filter,
                    )
                    validate_optional_range(
                        "Improvement ratio",
                        min_improvement_ratio_filter,
                        max_improvement_ratio_filter,
                    )
                    validate_optional_range(
                        "Land percentage",
                        min_land_value_ratio_filter,
                        max_land_value_ratio_filter,
                    )

                    results, output_path = run_search(
                        min_acres=min_acres,
                        max_acres=max_acres,
                        target_roads=target_roads,
                        buffer_feet=buffer_feet,
                        commercial_only=commercial_only,
                        city_status=city_status,
                        absentee_owners_only=absentee_owners_only,
                        min_appraised_value=min_appraised_value_filter,
                        max_appraised_value=max_appraised_value_filter,
                        min_improvement_ratio=min_improvement_ratio_filter,
                        max_improvement_ratio=max_improvement_ratio_filter,
                        min_land_value_ratio=min_land_value_ratio_filter,
                        max_land_value_ratio=max_land_value_ratio_filter,
                    )

                st.session_state["results"] = results
                st.session_state["output_path"] = output_path
            except Exception as exc:
                st.error(str(exc))
else:
    st.info(
        "Enter search criteria and click Run search. Results will be saved in the outputs folder."
    )

if "results" in st.session_state and "output_path" in st.session_state:
    results = st.session_state["results"]
    output_path = st.session_state["output_path"]
    table_results = results_for_csv(results)

    st.success(f"Found {len(results)} parcels. Saved to {output_path}")

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    commercial_count = (
        table_results["Type"].fillna("").str.contains("Commercial", case=False).sum()
    )
    average_acreage = table_results["CALC_ACRE"].mean()

    metric_col1.metric("Total results", f"{len(table_results):,}")
    metric_col2.metric("Commercial parcels", f"{commercial_count:,}")
    metric_col3.metric("Average acreage", f"{average_acreage:.2f}")

    csv_data = table_results.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv_data,
        file_name=output_path.name,
        mime="text/csv",
    )

    keyed_table_results = get_parcel_key_frame(table_results)
    selection_table = keyed_table_results.copy()
    selection_table.insert(0, "select_for_enrichment", False)

    st.caption(
        "Use the checkbox column or the parcel selector below to choose parcels for highlighting and manual enrichment."
    )
    edited_selection_table = st.data_editor(
        selection_table,
        use_container_width=True,
        hide_index=True,
        disabled=[
            column
            for column in selection_table.columns
            if column != "select_for_enrichment"
        ],
        column_config={
            "select_for_enrichment": st.column_config.CheckboxColumn(
                "Select",
                help="Select parcels to highlight and enrich.",
            ),
            "cad_lookup_link": st.column_config.LinkColumn(
                "CAD lookup link",
                display_text=CAD_LINK_LABEL,
            ),
        },
        key=f"results_selector_{output_path.name}",
    )

    selected_from_table = edited_selection_table.loc[
        edited_selection_table["select_for_enrichment"] == True,
        "parcel_key",
    ].tolist()

    if results.empty:
        st.info("No parcels to map.")
    else:
        st.subheader("Parcel Map")
        parcel_options = keyed_table_results["parcel_key"].drop_duplicates().tolist()
        selected_from_map = st.multiselect(
            "Highlight / enrich selected parcels",
            options=parcel_options,
            default=selected_from_table,
        )
        selected_parcels = sorted(set(selected_from_table) | set(selected_from_map))
        parcel_map = make_parcel_map(results, selected_parcels)
        st_folium(parcel_map, use_container_width=True, height=600)

        st.subheader("Enrich Selected Parcels")
        if not selected_parcels:
            st.info("Select parcels above to add manual ownership and value details.")
        else:
            enrichment_source = keyed_table_results[
                keyed_table_results["parcel_key"].isin(selected_parcels)
            ].copy()

            for column in MANUAL_ENRICHMENT_COLUMNS:
                if column not in enrichment_source.columns:
                    enrichment_source[column] = pd.NA

            enrichment_editor_data = enrichment_source[
                MANUAL_ENRICHMENT_COLUMNS
            ].copy()
            edited_enrichment = st.data_editor(
                enrichment_editor_data,
                use_container_width=True,
                hide_index=True,
                disabled=[
                    "ACCOUNT",
                    "PARCELID",
                    "ADDRESS",
                    "POSTAL_CIT",
                    "cad_lookup_link",
                ],
                column_config={
                    "cad_lookup_link": st.column_config.LinkColumn(
                        "CAD lookup link",
                        display_text=CAD_LINK_LABEL,
                    ),
                    "appraised_value": st.column_config.NumberColumn(
                        "appraised_value",
                        min_value=0,
                        step=1000,
                    ),
                    "land_value": st.column_config.NumberColumn(
                        "land_value",
                        min_value=0,
                        step=1000,
                    ),
                    "improvement_value": st.column_config.NumberColumn(
                        "improvement_value",
                        min_value=0,
                        step=1000,
                    ),
                },
                key=f"manual_enrichment_{output_path.name}",
            )

            if st.button("Save manual enrichment"):
                save_manual_enrichment(edited_enrichment)
                st.success(f"Saved {len(edited_enrichment)} records to {MANUAL_ENRICHMENT_PATH}")
