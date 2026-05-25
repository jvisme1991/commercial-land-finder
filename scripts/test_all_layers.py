import geopandas as gpd

parcels = gpd.read_file(
    r"G:\programs\commercial-land-finder\data\parcels\target parcels.shp"
)

roads = gpd.read_file(
    r"G:\programs\commercial-land-finder\data\roads\Road_Centerline.shp"
)

city_limits = gpd.read_file(
    r"G:\programs\commercial-land-finder\data\city_limits\City_Limits.shp"
)

print("\nPARCEL COLUMNS:")
print(parcels.columns)

print("\nROAD COLUMNS:")
print(roads.columns)

print("\nCITY LIMIT COLUMNS:")
print(city_limits.columns)

print("\nLAYER COUNTS:")
print(f"Parcels: {len(parcels)}")
print(f"Roads: {len(roads)}")
print(f"City Limits: {len(city_limits)}")