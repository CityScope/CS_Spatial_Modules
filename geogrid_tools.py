import urllib
import json
import geopandas as gpd
from shapely.geometry import Point
import requests

post_headers  = {'Content-Type': 'application/json'}

def init_geogrid(table_name, interactive_zone=None):
    """
    initialises the available types on the front-end to a default list from text file
    initialises the GEOGRIDDATA to all "None"
    """

    get_url='https://cityio.media.mit.edu/api/table/'+table_name
    post_url='https://cityio.media.mit.edu/api/table/'+table_name
    with urllib.request.urlopen(get_url+'/GEOGRID') as url:
        geogrid=json.loads(url.read().decode()) 
    default_types=json.load(open('data/default_types.json'))
    geogrid['properties']['types']=default_types

    if interactive_zone is not None:
        with urllib.request.urlopen(get_url+'/GEOGRID') as url:
            geogrid_gpd=gpd.read_file(url.read().decode())
        geogrid_intersect_interactive=gpd.overlay(geogrid_gpd, interactive_zone)
        intersect_ids=geogrid_intersect_interactive['id'].values
    else:
        intersect_ids=list(range(len(geogrid['features'])))

    for i in range(len(geogrid['features'])):
        geogrid['features'][i]['properties']['name']='None'
        geogrid['features'][i]['properties']['height']=[0]
        if i in intersect_ids:
            geogrid['features'][i]['properties']['interactive']='Web'
            geogrid['features'][i]['properties']['color']=[150,150,150,150]
        else:
            geogrid['features'][i]['properties']['interactive']=False
            geogrid['features'][i]['properties']['color']=[0,0,0,0]
            
    r = requests.post(post_url+'/GEOGRID/', data = json.dumps(geogrid), headers=post_headers)
    print('Initialise GEOGRID: {}'.format(r))
    return geogrid['properties']
    
def identify_state(properties):
    # TODO: if table already existed, just load state from text file
    print('Downloading state outlines')
    state_outlines=gpd.read_file(
        'https://www2.census.gov/geo/tiger/TIGER2019/STATE/tl_2019_us_state.zip')
    state_outlines=state_outlines.to_crs("EPSG:4326")
    table_lon, table_lat=properties['header']['longitude'], properties['header']['latitude']
    table_Point=Point(table_lon, table_lat)
    for ind, row in state_outlines.iterrows():
        if row['geometry'].contains(table_Point):
            return row['GEOID']
    return None

def assign_sim_area(geogrid, zones):
    """
    find the baseline zones which overlap with the geogrid
    these are the simulation area
    """
    zones['copy_GEOID']=zones.index.copy()
    grid_intersect_zones=gpd.overlay(geogrid, zones, 'intersection')
    zones['sim_area']=zones.index.isin(grid_intersect_zones['copy_GEOID'].unique())
    return zones


def select_geom_by_overlap_threshold(areas_to_filter, 
                                     filter_with, 
                                     area_id_col,
                                     min_prop=0.5):
    """ identify areas in one GeoDataFrame which have a percentage overlap 
    with another GeoDataFrame
    at least as great as the minimum specified"""
    areas_to_filter['zone_area']=areas_to_filter.geometry.area
    all_intersect=gpd.overlay(areas_to_filter, filter_with, 'intersection')
    all_intersect['intersect_area']=all_intersect.geometry.area
    all_intersect=all_intersect[[col for col in all_intersect if not col=='zone_area']]
    all_intersect=all_intersect.merge(areas_to_filter[[area_id_col, 'zone_area']], 
                                    how='left', left_on=area_id_col, right_on=area_id_col)
    all_intersect['prop_area']=all_intersect['intersect_area']/all_intersect['zone_area']
    valid_intersect=all_intersect.loc[all_intersect['prop_area']>min_prop]
    valid_ids=list(valid_intersect[area_id_col])
    return valid_ids


def init_geogrid(table_name, types, interactive_zone=None):
    """
    initialises the available types on the front-end to a default list from text file
    initialises the GEOGRIDDATA to all "None"
    """

    get_url='https://cityio.media.mit.edu/api/table/'+table_name
    post_url='https://cityio.media.mit.edu/api/table/'+table_name
    with urllib.request.urlopen(get_url+'/GEOGRID/') as url:
        geogrid=json.loads(url.read().decode()) 
    geogrid['properties']['types']=types

    if interactive_zone is not None:
        with urllib.request.urlopen(get_url+'/GEOGRID') as url:
            geogrid_gpd=gpd.read_file(url.read().decode())
        geogrid_intersect_interactive=gpd.overlay(geogrid_gpd, interactive_zone)
        intersect_ids=geogrid_intersect_interactive['id'].values
    else:
        intersect_ids=list(range(len(geogrid['features'])))

    for i in range(len(geogrid['features'])):
        geogrid['features'][i]['properties']['name']='None'
        geogrid['features'][i]['properties']['height']=[0]
        if i in intersect_ids:
            geogrid['features'][i]['properties']['interactive']='Web'
            geogrid['features'][i]['properties']['color']=geogrid['properties']['types']['None']['color']
        else:
            geogrid['features'][i]['properties']['interactive']=False
            geogrid['features'][i]['properties']['color']=[0,0,0,0]
            
    r = requests.post(post_url+'/GEOGRID/', data = json.dumps(geogrid), headers=post_headers)
    print('Initialise GEOGRID: {}'.format(r))
    return geogrid['properties']