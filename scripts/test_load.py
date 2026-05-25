import geopandas as gpd

# Load parcel shapefile
parcels = gpd.read_file(
    r"G:\programs\commercial-land-finder\data\parcels\target parcels.shp"
)

# Print column names
print("\nPARCEL COLUMNS:\n")
print(parcels.columns)

# Print first few rows
print("\nFIRST 5 ROWS:\n")
print(parcels.head())