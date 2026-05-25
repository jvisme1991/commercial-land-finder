# Commercial Land Finder

A simple local Streamlit app for finding commercial land prospects from local GIS layers.

The app loads parcels, roads, and city limits from the `data` folder, runs the same GIS filtering logic as `scripts/run_search.py`, scores matching parcels, shows the results in a table, and saves CSV files to `outputs`.

## Project Structure

- `app.py` - Streamlit app
- `scripts/run_search.py` - reusable GIS search logic and command-line runner
- `data/parcels/target parcels.shp` - parcel layer
- `data/roads/Road_Centerline.shp` - road centerline layer
- `data/city_limits/City_Limits.shp` - city limits layer
- `data/ownership/` - optional ownership/appraisal CSV files
- `outputs/` - saved CSV search results

## Search Inputs

- Minimum acres
- Maximum acres
- Target road names
- Road buffer distance in feet
- Commercial only yes/no
- City status: any, inside city limits, or outside city limits
- Absentee owners only yes/no
- Minimum and maximum appraised value
- Minimum and maximum improvement ratio percentage
- Minimum and maximum land percentage

For appraisal range filters, use `0` or leave the field blank for no limit. The default maximum percentage value of `100` also means no upper limit.

## Ownership and Appraisal Data

Place ownership/appraisal CSV files in `data/ownership`. The app joins them to parcels by `ACCOUNT` or `PARCELID`.

The CSV can use common column names for owner, mailing address, mailing city, appraised value, land value, and improvement value. Results include absentee owner, improvement ratio, and land-to-total-value ratio calculations.

The app also creates `data/ownership/manual_enrichment.csv` for manual CAD lookup work. Select parcels from the results table or map selector, open the CAD lookup link, enter owner/value details in the enrichment editor, and save. Future searches automatically merge those saved records by `ACCOUNT`.

## Scoring

Matching parcels are scored with the existing simple rules:

- 20 points for parcels between 1 and 5 acres
- 20 points for commercial parcel type
- 10 points for parcels inside city limits
- 10 points for absentee owners
- 15 points for low improvement value
- 15 points for high land percentage

## Install

From the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If your PowerShell policy blocks activation, use:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run the App

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

Then open the local URL Streamlit prints, usually:

```text
http://localhost:8501
```

## Run the Original Script

The command-line script still works and writes `outputs/land_search_results.csv`:

```powershell
.\.venv\Scripts\python.exe scripts\run_search.py
```

## Outputs

Each app search saves a timestamped CSV in `outputs`, and the app also provides a CSV download button.

Search results also include summary metrics and an interactive Folium map with parcel popups for acreage, address, parcel ID, and score.
