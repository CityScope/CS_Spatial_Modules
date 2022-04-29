import osmnet
import pandana
import geopandas as gpd
import pandas as pd
import numpy as np
from scipy.spatial import KDTree
import datetime
from brix import Indicator


def get_projection_gdf(geom):
    longitude=sum([c.x for c in geom.geometry.centroid])/len(geom)
    utm_zone = int(np.floor((longitude + 180) / 6) + 1)
    crs = f"+proj=utm +zone={utm_zone} +ellps=WGS84 +datum=WGS84 +units=m +no_defs"
    return crs

def get_buffered_outline(geom, buffer):
    proj_crs=get_projection_gdf(geom)
    geom_projected=geom.to_crs(proj_crs)
    geom_projected_buffered=geom_projected.unary_union.buffer(buffer)
    geom_projected_buffered_gdf=gpd.GeoDataFrame(
        geometry=[geom_projected_buffered], crs=geom_projected.crs)
    geom_buffered_gdf=geom_projected_buffered_gdf.to_crs(geom.crs)
    return geom_buffered_gdf

def get_overlap_by_threshold(geom_1, geom_2, threshold=0.5):
    """
    function for subsetting a polygon collection based on overlap with another polygon collection
    geom_1 and geom_2 should be geopandas GeoDataFrames
    geom_1 is the geometry to be subsetted
    subsetting is based on overlap with geom_2
    a zone in geom_1 will be included in the output if its area of overlap with geom_2 is greater than the threshold
    """
    geom_1['copy_index']=geom_1.index
    geom_1['zone_area']=geom_1.geometry.area
    all_intersect=gpd.overlay(geom_2.to_crs(geom_1.crs), geom_1, 'intersection')
    all_intersect['intersect_area']=all_intersect.geometry.area
    all_intersect=all_intersect[[col for col in all_intersect.columns if not col=='zone_area']]
    all_intersect=all_intersect.merge(geom_1[['copy_index', 'zone_area']],
        how='left', left_on='copy_index', right_on='copy_index')
    all_intersect['prop_area']=all_intersect['intersect_area']/all_intersect['zone_area']
    valid_intersect=all_intersect.loc[all_intersect['prop_area']>threshold]
    final_zone_ids=list(valid_intersect['copy_index'])
    return final_zone_ids

def get_target_capacities(row, cell_area):
    height=row['height']
    if isinstance(height, list):
        height=height[0]
    cell_name=row['name']
    total_area=cell_area*height
    if 'sqm_pperson' in row:
        sqm_pperson=row['sqm_pperson']
    else:
        sqm_pperson=100
    row[cell_name]=total_area/sqm_pperson
    return row

class prox_model():
    def __init__(self, places, max_dist, target_settings,
                network_type='walk'):
        self.max_dist=max_dist
        self.places=places
        self.network_type=network_type
        self.target_settings=target_settings
          
        self.get_network(impact_area=places.loc[places['source']])
        self.find_closest_nodes()
        self.build_dist_mat()
        
    def get_network(self, impact_area):
        print('Getting network inside buffered outline from OSM')
        buffer_outline=get_buffered_outline(impact_area, self.max_dist)
        bbox=tuple(buffer_outline.total_bounds)
        self.nodes_df, self.edges_df=osmnet.load.network_from_bbox(
            bbox=bbox,network_type=self.network_type, two_way=True)
        self.net=pandana.Network(self.nodes_df["x"], self.nodes_df["y"], 
                                      self.edges_df["from"], self.edges_df["to"],
                 self.edges_df[["distance"]])
        
    def find_closest_nodes(self):
        print('Finding closest nodes to each place')
        nodes_gdf=gpd.GeoDataFrame(
            data=[], index=self.nodes_df.index, 
            geometry=gpd.points_from_xy(
                x=self.nodes_df['x'], 
                y=self.nodes_df['y']), 
            crs='EPSG:4326')
        nodes_crs=get_projection_gdf(nodes_gdf)
        nodes_gdf_projected=nodes_gdf.to_crs(nodes_crs)  
        nodes_kdtree=KDTree([[p.x, p.y] for p in nodes_gdf_projected.geometry])
        places_proj=self.places.to_crs(nodes_crs)
        dist, ind_nearest=nodes_kdtree.query([[c.x, c.y] for c in places_proj.geometry.centroid])
        nearest_nodes=[nodes_gdf_projected.index[i] for i in ind_nearest]
        return dist, nearest_nodes
        
    def build_dist_mat(self):
        print('Building distance matrix')
        dist_to_nearest_nodes, nearest_nodes=self.find_closest_nodes()
        self.places['nearest_nodes']=nearest_nodes
        self.places['dist_to_nearest_nodes']=dist_to_nearest_nodes
        source_places=self.places.loc[self.places['source']==True]
        dist_mat=[]
        for ind, row in source_places.iterrows():
            origin_nodes=[row['nearest_nodes']]*len(self.places)
            dest_nodes=nearest_nodes
            path_lengths=self.net.shortest_path_lengths(origin_nodes, dest_nodes)
            path_lengths_with_ends=np.array(path_lengths)+np.array(dist_to_nearest_nodes)+row['dist_to_nearest_nodes']
            dist_mat.append(list(path_lengths_with_ends))
        self.dist_mat=np.array(dist_mat)
        self.reachable_mat=self.dist_mat<self.max_dist
        
    def calculate_access(self, places_data):
        access = np.dot(self.reachable_mat, np.array(places_data[[self.target_settings[t]['column'] for t in self.target_settings]]))
        access_df=pd.DataFrame(access, columns=[t for t in self.target_settings])
        return access_df

    def get_heatmap(self, places_data, access_df):
        access_gdf=gpd.GeoDataFrame(data=access_df, geometry=list(places_data.geometry), crs=places_data.crs)
        for t in self.target_settings:
            access_gdf[t+'_norm']=np.minimum(1,access_gdf[t]/self.target_settings[t]['max'])
        return access_gdf
  
    def weighted_access(self, places_data, access_df):
        target_list=list(self.target_settings.keys())
        sources=np.array(places_data.loc[places_data['source'], [self.target_settings[t]['from'] for t in target_list]])
        access=np.array(access_df[[t for t in target_list]])
        weighted_access=np.multiply(access, sources).sum(axis=0)/sources.sum(axis=0)
        scores_dict={t: {'raw': weighted_access[i], 'norm': min(1, weighted_access[i]/self.target_settings[t]['max'])} for i, t in enumerate(target_list)}
        return scores_dict


class Proximity_Indicator(Indicator):
    def setup(self, static_places, geogrid, max_dist, target_settings,
             code_res=2):
        self.requires_geometry = True
        self.code_res=code_res
        self.indicator_type = 'hybrid'
        geogrid['source']=True
        static_places['source']=False
        static_places.loc[get_overlap_by_threshold(static_places, 
                                                   gpd.GeoDataFrame(geometry=[geogrid.unary_union], crs=geogrid.crs), 
                                                   threshold=0.5), 'source']=True
        self.static_places=static_places
        places=pd.concat([static_places, geogrid], axis=0)
#         self.places=places
        
        self.prox_model=prox_model(places=places, max_dist=max_dist, 
             target_settings=target_settings, network_type='walk')
        
        access_df=self.prox_model.calculate_access(places.fillna(0))
        self.baseline_scores=self.prox_model.weighted_access(places.fillna(0), access_df)
        
    def update_target_settings(target_settings):
        self.prox_model.target_settings=target_settings

    def get_cs_heatmap(self, heatmap):
        cs_heatmap=heatmap.__geo_interface__
        target_list=[t for t in self.target_settings]
        cs_heatmap['properties']=target_list
        for i_f in range(len(cs_heatmap['features'])):
            prox_list=[feat['properties']['{}_norm'.format(t)] for t in target_list]
            cs_heatmap['features'][i_f]['properties']=prox_list
        return cs_heatmap
        
    def return_indicator(self, geogrid_data):
        start_time=datetime.datetime.now()
        geogrid_data_df=geogrid_data.as_df()
        geogrid_data_df['source']=True
        type_def=geogrid_data.get_type_info()
        cell_area=(geogrid_data.get_geogrid_props()['header']['cellSize'])**2

        # Add columns to each row (grid cell) for this row's capacity of each CS_type and each naics and lbcs code
        geogrid_data_df=geogrid_data_df.apply(lambda row: get_target_capacities(row, cell_area), axis=1)
        present_types=[t for t in type_def if t in geogrid_data_df.columns]
        for type_name in present_types:
            for attr in ['NAICS', 'LBCS']:
                if type_def[type_name][attr] is not None:
                    for code in type_def[type_name][attr]:
                        col_name='{}_{}'.format(attr.lower(), code[:self.code_res])
                        if col_name not in geogrid_data_df.columns:
                            geogrid_data_df[col_name]=0
                        code_prop=type_def[type_name][attr][code]
                        geogrid_data_df[col_name]+=geogrid_data_df[type_name]*code_prop
                        
        # get total residents and total employees
        res_cols=[col for col in geogrid_data_df if col.startswith('lbcs_1')]
        emp_cols=[col for col in geogrid_data_df if col.startswith('naics_')]
        geogrid_data_df['res_total']=geogrid_data_df[res_cols].sum(axis=1)
        geogrid_data_df['emp_total']=geogrid_data_df[emp_cols].sum(axis=1)
        
        # convert naics/lbcs cols to same resolution as the targets
        target_settings=self.prox_model.target_settings
        naics_targets=[target_settings[t]['column'] for t in target_settings if 'naics' in target_settings[t]['column']]
        for nt in naics_targets:
            print(nt)
            code_range = nt.split('emp_naics_')[1].split('-')
            all_codes= list(range(int(code_range[0]), int(code_range[-1])+1))
            all_cols=['naics_{}'.format(code) for code in all_codes]
            geogrid_data_df[nt]=geogrid_data_df[
                [col for col in all_cols if col in geogrid_data_df.columns]].sum(axis=1)
            
        # Concatenate the baseline static data with the updated geogrid data
        updated_places=pd.concat([self.static_places, geogrid_data_df]).fillna(0)

        # calculate the new accessibility based on the updated geogrid data
        access_df=self.prox_model.calculate_access(updated_places)
        scores=self.prox_model.weighted_access(updated_places, access_df)
        
        result=[{'name': '{} Proximity'.format(t).title(), 
                 'value': scores[t]['norm'],
                 'raw_value': scores[t]['raw'], 
                 'ref_value': self.baseline_scores[t]['norm']} for t in scores]
        print('Proximity calculation took {} seconds'.format(datetime.datetime.now() - start_time))

        heatmap=self.prox_model.get_heatmap(access_df)
        cs_heatmap=self.get_cs_heatmap(heatmap)
        return {'heatmap':cs_heatmap,'numeric':result}