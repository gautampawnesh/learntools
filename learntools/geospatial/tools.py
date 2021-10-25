from geopy.point import Point
import geopandas as gpd

all_addresses = ['2224 Shattuck Avenue Berkeley CA',
                 '1799 Solano Avenue Berkeley CA',
                 '1444 Shattuck Place Berkeley CA',
                 '3001 Telegraph Avenue Berkeley CA',
                 '2128 Oxford Street Berkeley CA']

class Nominatim:
    def __init__(self, user_agent):
        self.user_agent = user_agent
    def geocode(self, address):
        try:
            my_index = all_addresses.index(address)
            gdf = gpd.read_file("../input/geospatial-learn-course-data/ex4_files/ex4_files/add_{}.shp".format(my_index))
            return Point(latitude=gdf.geometry.y, longitude=gdf.geometry.x)
        except:
            return None