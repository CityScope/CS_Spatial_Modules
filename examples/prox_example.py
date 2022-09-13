import sys
sys.path.append('../')

from Proximity import prox_model, Proximity_Indicator
from brix import Indicator, Handler, Grid_maker
import datetime
import geopandas as gpd
import json
import requests

table_name='epa'
H=Handler(table_name)

geogrid=H.get_geogrid_data(include_geometries=True).as_df()
zones=gpd.read_file('../tables/epa/zones.geojson')

target_settings={'housing': {'column': 'res_total','max': 100000, 'from': 'emp_total'},
                 'healthcare': {'column': 'emp_naics_62','max': 10000, 'from': 'res_total'},
                 'jobs': {'column': 'emp_total','max': 100000, 'from': 'res_total'},
                'shopping': {'column': 'emp_naics_44-45','max': 10000, 'from': 'res_total'},
                'education': {'column': 'emp_naics_61','max': 10000, 'from': 'res_total'},
                'entertainment': {'column': 'emp_naics_71','max': 10000, 'from': 'res_total'}}

p=Proximity_Indicator(static_places=zones, geogrid=geogrid, 
      max_dist=2400, target_settings=target_settings)

H.add_indicator(p)
H.listen()