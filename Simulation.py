#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Dec 22 16:32:27 2020

@author: doorleyr
"""

import pandas as pd
import geopandas as gpd
import numpy as np
import math
import random
from shapely.geometry import Point, LineString
import json
import os

def coord_list_to_line_string(coordinates):
    if len(coordinates)>1:
        return LineString(coordinates)
    elif len(coordinates)>0:
        return Point(coordinates)
    else:
        return None


class Default_Mode_Choice_model():
    def __init__(self):
        pass
    
    def predict_modes(self, all_trips_df):
        options=['drive', 'cycle', 'walk', 'pt']
        all_trips_df['mode']=np.random.choice(
            options, size=len(all_trips_df), 
            replace=True, p=[0.6, 0.1, 0.2, 0.1])
        return all_trips_df

class PdnaNetwork():
    """
    a wrapper around a pandana network object
    which adds some additional methods

    """
    def __init__(self, network):
        self.net=network
        self.build_link_attribute_lookup()

    def build_link_attribute_lookup(self):
        print("building link attribute lookup")
        self.attr_lookup={}
        edges_df=self.net.edges_df.copy()
        if self.net._twoway:
            temp=edges_df.set_index(['to', 'from'], drop=False)
            temp['from']=list(edges_df['to'].values)
            temp['to']=list(edges_df['from'].values)
            edges_df=edges_df.append(temp)
            # eliminate duplicates, keeping the lowest of each weight metric
            # in general other attributes are the same for each duplicate
            # note that for other attributes which differ across links with the same a and b nodes (like link type)
            # this approach may give incorrect results.
        weight_metrics= self.net.impedance_names
        agg_dict={weight: 'min' for weight in weight_metrics}
        for col in edges_df.columns:
            if col not in weight_metrics:
                agg_dict.update({col: lambda x: x.iloc[0]})
        edges_df=edges_df.groupby(edges_df.index).agg(agg_dict)
        # add node coordinates
        edges_df=edges_df.join(self.net.nodes_df, how='left', on='from').rename(
            columns={'x': 'a_node_x', 'y': 'a_node_y'})
        edges_df=edges_df.join(self.net.nodes_df, how='left', on='to').rename(
            columns={'x': 'b_node_x', 'y': 'b_node_y'})
        self.attr_lookup=edges_df.to_dict(orient='index')

    def get_nodes_df(self):
        return self.net.nodes_df

    def get_node_ids(self, x_col,y_col):
        return self.net.get_node_ids(x_col,y_col)

    def shortest_paths(self, nodes_a, nodes_b, imp_name):
        return self.net.shortest_paths(nodes_a, nodes_b, imp_name)

    def get_path_link_attributes(self, path, attribute_names):
        # attribute_names=self.net.impedance_names
        output={attr: [] for attr in attribute_names}
        if len(path)>1:
            coordinates=[]
            edges=[]
            for node_ind in range(len(path)-1):
                from_node=path[node_ind]
                to_node=path[node_ind+1]
                edges.append((from_node, to_node))
                this_link_attrs=self.attr_lookup[(from_node, to_node)]
                for attr in attribute_names:
                    output[attr].append(this_link_attrs[attr])
                coordinates+=[[this_link_attrs['a_node_x'], this_link_attrs['a_node_y']]]
            coordinates+=[[this_link_attrs['b_node_x'], this_link_attrs['b_node_y']]]
            output['coordinates']=coordinates
            output['edges']=edges
            return output
        else:
            output['coordinates']=[]
            output['edges']=[]
            return output

class MobilitySystem():
    def __init__(self, modes, networks):
        """
        modes should be a dictionary with the identifier as key 
        and the mode object as value
        networks should be a dictionary where keys are network ids and values 
        are network objects
        """
        assert all(modes[m].target_network_id in networks.keys() for m in modes), "A network ID doesn't exist"
        self.modes = modes
        self.networks = networks

    # def get_one_route(self, mode_id, node_a, node_b, include_attributes=False):
    #     target_network_id=self.modes[mode_id].target_network_id
    #     travel_time_metric=self.modes[mode_id].travel_time_metric
    #     node_path= self.networks[target_network_id].shortest_path(
    #             node_a, node_b, imp_name=travel_time_metric)
    #     if include_attributes==True:
    #         attributes=self.get_path_link_attributes(node_path, target_network_id)
    #         return {'node_path': node_path, 'attributes': attributes}
    #     return node_path       
    
    def get_many_routes(self, mode_id, nodes_a, nodes_b, include_attributes=False):
        target_network_id=self.modes[mode_id].target_network_id
        travel_time_metric=self.modes[mode_id].travel_time_metric
        node_paths= self.networks[target_network_id].shortest_paths(
                nodes_a, nodes_b, imp_name=travel_time_metric)
        if include_attributes==True:
            attribute_names=[travel_time_metric]
            attributes=[self.networks[target_network_id].get_path_link_attributes(np, attribute_names=attribute_names) for np in node_paths]
            return {'node_path': node_paths, 'attributes': attributes}
        else:
            return node_paths           

class Mode():
    def __init__(self, mode_dict):
        """
        mode_dict must include at minimum:
            network_id: the network this mode uses
            weight_metric: the relevant weight metric of the target network (eg. distance)
        
        """
        self.mode_dict=mode_dict
        self.target_network_id=mode_dict['target_network_id']
        self.travel_time_metric=mode_dict['travel_time_metric']

# class Zones():
#     def __init__(self, zones_gdf, geoid_col=None):
#         """
#         If the index if not the geoid, then the geoid_col should be specified
#         """       
#         # TODO: support geojson?
#         zones_gdf_centroid=zones_gdf["geometry"].centroid
#         zones_gdf['x_centroid']=[c.x for c in zones_gdf_centroid]
#         zones_gdf['y_centroid']=[c.y for c in zones_gdf_centroid]
#         if geoid_col is not None:
#             zones_gdf=zones_gdf.set_index(geoid_col)
#         self.gdf=zones_gdf

class Simulation():
    def __init__(self, sim_pop, mob_sys, zones,  sim_geoids=None, person_attributes=None, mode_descriptions=None, profile_descriptions=None):
        # self.scheduler=self.default_scheduler
        # self.location_chooser=self.default_location_chooser
        self.mode_chooser=Default_Mode_Choice_model()
        self.check_zones(sim_pop, zones)           
        self.mob_sys=mob_sys
        self.zones=zones
        self.sim_geoids=sim_geoids
        self.mode_descriptions=mode_descriptions
        self.profile_descriptions=profile_descriptions
        # self.centre_x_y=centre_x_y
        # self.vis_radius=vis_radius
        self.get_internal_node_tables()
        self.get_close_node_table()
        self.assign_nodes_to_zones()
        # if needs_dist_mat:
        #     self.create_zone_dist_mat()
        if person_attributes==None:
            person_attributes=[col for col in sim_pop.columns if col not in [
                        'home_geoid', 'work_geoid']]+['mode']
        self.person_attributes=person_attributes
        # if ((centre_x_y is not None) and (vis_radius is not None)):
        #     self.get_vis_nodes()
        
    # def get_vis_nodes(self):
    #     print('Finding visible nodes')
    #     self.vis_nodes={}
    #     for net in self.mob_sys.networks:
    #         self.vis_nodes[net]=[ind for ind, row in self.mob_sys.networks[net].net.nodes_df.iterrows(
    #         ) if get_haversine_distance([row['x'], row['y']], self.centre_x_y)<self.vis_radius]
  
    def get_simpop_subset(self, sim_pop, sample_N=None):
        """
        People who live OR work in one of the sim_geoids will be included

        """

        sim_pop=sim_pop.reset_index(drop=True)
        if self.sim_geoids is not None:
            sim_pop=sim_pop.loc[((sim_pop['home_geoid'].isin(self.sim_geoids))|
                          (sim_pop['work_geoid'].isin(self.sim_geoids)))]
        if sample_N is not None:
            if len(sim_pop)>sample_N:
                sim_pop=sim_pop.sample(n=sample_N)
        return sim_pop
        
    def get_od_flows(self, sim_pop):
        return sim_pop.groupby(['home_geoid', 'work_geoid']).size()
    
    def get_zone_coords(self):
        return self.zones[['x_centroid', 'y_centroid']]
    
    def check_zones(self, sim_pop, zones):
        all_zones_sim_pop=set(list(sim_pop['home_geoid'])+list(sim_pop['work_geoid']))
        assert all(zone in zones.index for zone in all_zones_sim_pop)
        
    def get_close_node_table(self):
        """
        Creates a lookup table for each network, mapping zone geoids to closest node ids
        returns a dataframe with a column for each network, indexed by zone geoid
        """
        print('Finding closest nodes to every zone centroid')
        
        close_nodes={}
        for net in self.mob_sys.networks:
            close_nodes['node_'+net]=self.mob_sys.networks[net].get_node_ids(
                x_col=self.zones['x_centroid'],y_col=self.zones['y_centroid'])            
        self.close_nodes_df=pd.DataFrame(index=self.zones.index, data=close_nodes)

    def get_internal_node_tables(self):
        print('Getting internal nodes')
        self.zones['copy_GEOID']=self.zones.index.copy()
        self.internal_nodes={}
        for net in self.mob_sys.networks:
            nodes_df=self.mob_sys.networks[net].get_nodes_df()
            nodes_geodf=gpd.GeoDataFrame(nodes_df,
                                        geometry=gpd.points_from_xy(nodes_df.x, nodes_df.y),
                                        crs="EPSG:4326")
            nodes_geodf['node_id']=nodes_geodf.index
            
            zones_intersect_nodes=gpd.overlay(self.zones,nodes_geodf, 'intersection', keep_geom_type=False)
            nodes_by_geoid=zones_intersect_nodes.groupby('copy_GEOID').agg({'node_id': lambda nodes: [n for n in nodes]})
            self.internal_nodes[net]=nodes_by_geoid

    def assign_nodes_to_zones(self):
        self.zones=self.zones.join(self.close_nodes_df)
        for net in self.mob_sys.networks:
            self.zones=self.zones.join(self.internal_nodes[net]).rename(columns={'node_id': 'nodes_internal_{}'.format(net)})
            self.zones['possible_nodes_{}'.format(net)]=self.zones.apply(
                    lambda row: row['nodes_internal_{}'.format(net)] if isinstance(row['nodes_internal_{}'.format(net)], list
                        ) else [row['node_{}'.format(net)]], axis=1)

  
    # def default_scheduler(self, sim_pop_row):
    #     """
    #     gives everyone a schedule of [home, work, other, work, home]
    #     """
    #     sim_pop_row['activities']=['H', 'W', 'O','W','H']
    #     durations_hrs= [6+4*random.random(), # starts work between 6am and 1pm
    #                3+2*random.random(), # works for 3-5 hours
    #                0.5+1*random.random(), # break between 0.5 and 1.5 hours
    #                3+2*random.random()] # works for 3-5 hours
    #     sim_pop_row['start_times']=[0] + list(3600*np.cumsum(durations_hrs))
    #     return sim_pop_row
    
#     def default_mode_chooser(self, all_trips_df):
#         """
#         Input is entire trip table- modifies and returns the table
#         """
#         print("Choosing modes")
#         all_trips_df['mode']='drive'
# #         all_trips_df['net']='drive'
        
#         return all_trips_df
    
    # def default_location_chooser(self, sim_pop_row, zones):
    #     locations=[]
    #     for activity in sim_pop_row['activities']:
    #         if activity=='H':
    #             locations.append(sim_pop_row['home_geoid'])
    #         elif activity=='W':
    #             locations.append(sim_pop_row['work_geoid'])
    #         else:
    #             if self.sim_geoids is None:
    #                 locations.append(random.choice(zones.index))
    #             else:
    #                 locations.append(random.choice(self.sim_geoids))
    #     sim_pop_row['locations']=locations
    #     return sim_pop_row
        
    def set_choice_models(self, scheduler=None, location_chooser=None, mode_chooser=None):
        """
        Replace default choice models with user-specified models
        """
        if scheduler is not None:
            self.scheduler=scheduler
        if location_chooser is not None:
            self.location_chooser=location_chooser
        if mode_chooser is not None:
            self.mode_chooser=mode_chooser
            
    # def create_activity_schedules(self, sim_pop):
    #     print("Scheduling activities")
    #     sim_pop=sim_pop.apply(lambda row: self.scheduler(row), axis=1)
    #     print("Choosing locations for each activity")
    #     sim_pop=sim_pop.apply(lambda row: self.location_chooser(row, self.zones), axis=1)
    #     return sim_pop


    def create_simple_HWH_schedules(self, simpop_df):
        simpop_df['activities']=[['H', 'W', 'H']]*len(simpop_df)
        durations_list=[8,9]
        durations_det=np.array([durations_list]*len(simpop_df))
        durations_rand=-0.25+0.5*np.random.rand(durations_det.shape[0], durations_det.shape[1])# between -0.25 and 0.25
        durations_rand_scaled=np.multiply(durations_rand,durations_list)
        durations_total=durations_det+durations_rand_scaled

        start_times=(3600*np.column_stack((np.zeros((len(simpop_df),1)), np.cumsum(durations_total, axis=1)))).astype(int)
        simpop_df['start_times']=[list(start_times[s,:]) for s in range(len(simpop_df))]

        simpop_df['locations']=simpop_df.apply(lambda row: [row['home_geoid'],
                                                        row['work_geoid'],
                                                        row['home_geoid']], axis=1)
        return simpop_df

    def create_simple_HWOWH_schedules(self, simpop_df):
        simpop_df['activities']=[['H', 'W', 'O', 'W', 'H']]*len(simpop_df)
        durations_list=[8,4,0.5,4]
        durations_det=np.array([durations_list]*len(simpop_df))
        durations_rand=-0.25+0.5*np.random.rand(durations_det.shape[0], durations_det.shape[1])# between -0.25 and 0.25
        durations_rand_scaled=np.multiply(durations_rand,durations_list)
        durations_total=durations_det+durations_rand_scaled

        start_times=(3600*np.column_stack((np.zeros((len(simpop_df),1)), np.cumsum(durations_total, axis=1)))).astype(int)
        simpop_df['start_times']=[list(start_times[s,:]) for s in range(len(simpop_df))]

        sim_zones=self.zones.loc[self.sim_geoids].copy()
        sim_zones['other_attraction']=sim_zones['emp_naics_72']+sim_zones['emp_naics_71']
        simpop_df['other_place']=sim_zones.sample(len(simpop_df), weights='other_attraction',replace=True).index

        simpop_df['locations']=simpop_df.apply(lambda row: [row['home_geoid'],
                                                        row['work_geoid'],
                                                        row['other_place'],
                                                        row['work_geoid'],
                                                        row['home_geoid']], axis=1)
        return simpop_df

    def create_trip_table(self, sim_pop):
        """
        For every person who passes through the simulation area:
            add all their trips to a trip table
        
        """
        all_trips=[]
        for ind, row in sim_pop.iterrows():
            activities=row['activities']
            start_times=row['start_times']
            locations=row['locations']
            for i in range(len(activities)-1):
                trip={'from_activity': activities[i],
                      'to_activity': activities[i+1],
                      'from_zone': locations[i],
                      'to_zone': locations[i+1],
                      'person_id': row.name,
                      'start_time': start_times[i+1]}
                for attr in self.person_attributes:
                    if attr in row:
                        trip[attr]=row[attr]
                all_trips.append(trip)
        all_trips_df=pd.DataFrame(all_trips)
        columns_to_join=[col for col in self.zones if 'possible' in col]
        # all_trips_df=all_trips_df.join(self.close_nodes_df, how='left', on='from_zone').rename(columns={
        #         'node_'+net: 'from_node_'+net for net in self.mob_sys.networks})
        # all_trips_df=all_trips_df.join(self.close_nodes_df, how='left', on='to_zone').rename(columns={
        #         'node_'+net: 'to_node_'+net for net in self.mob_sys.networks})
        all_trips_df=all_trips_df.join(self.zones[columns_to_join], how='left', on='from_zone').rename(columns={
            'possible_nodes_'+net: 'from_possible_nodes_'+net for net in self.mob_sys.networks})
        all_trips_df=all_trips_df.join(self.zones[columns_to_join], how='left', on='to_zone').rename(columns={
            'possible_nodes_'+net: 'to_possible_nodes_'+net for net in self.mob_sys.networks})
        return all_trips_df
    
    # TODO: if I'm ultimately always using the traversal tables (rather than route_table)
    # then I should rethink this process- there's no need to get attributes/coordinates for every time a link
    # is traversed if I'm then going to groupby link and just take the first instance for each.
    # just get the link ids with the person attributes. After the grouby operations, then get the
    # cordinates etc.
    # Edge weight is needed however for building the node traversal table
    # For the node traversals
    
    def get_routes_table(self, all_trips_df):
        route_table=pd.DataFrame()
        for mode_id in self.mob_sys.modes:
            target_network_id=self.mob_sys.modes[mode_id].target_network_id
            route_table_this_mode=all_trips_df.loc[(all_trips_df['mode']==mode_id)]
            sampled_from_nodes=route_table_this_mode.apply(lambda row: random.choice(row['from_possible_nodes_'+target_network_id]), axis=1)
            sampled_to_nodes=route_table_this_mode.apply(lambda row: random.choice(row['to_possible_nodes_'+target_network_id]), axis=1)
            routes=self.mob_sys.get_many_routes(
                mode_id, 
                sampled_from_nodes.values,
                sampled_to_nodes.values, 
                include_attributes=True)
            route_table_this_mode['node_path']=routes['node_path']
            route_table_this_mode['attributes']=routes['attributes']
            route_table=route_table.append(route_table_this_mode)
        return route_table

    def routes_to_deckgl_trip(self, route_table):
        legend={}
        if self.mode_descriptions is not None:
            mode_legend={}
            mode_id_map={self.mode_descriptions[i]['name']: i for i in range(len(self.mode_descriptions))}
            for i in range(len(self.mode_descriptions)):
                name=self.mode_descriptions[i]['name']
                mode_legend[str(i)]={"color": self.mode_descriptions[i]['color'],
                                    "name": "{} : {}%".format(name.title(),
                                                             100*sum(route_table['mode']==name)/len(route_table))}
            legend['mode']= mode_legend
        if self.profile_descriptions is not None:
            profile_legend={}
            profile_id_map={self.profile_descriptions[i]['name']: i for i in range(len(self.profile_descriptions))}
            for i in range(len(self.profile_descriptions)):
                name=self.profile_descriptions[i]['name']
                profile_legend[str(i)]={"color": self.profile_descriptions[i]['color'],
                                    "name": 'Income '+str(name)}
            legend['profile']= profile_legend
        
        trips=[]
        for ind, row in route_table.iterrows():
            coords=[[int(c[0]*1e5)/1e5, int(c[1]*1e5)/1e5] for c in row['attributes']['coordinates']]
            if len(coords)>1:
                travel_time_metric=self.mob_sys.modes[row['mode']].travel_time_metric
                cum_time=np.cumsum(row['attributes'][travel_time_metric])
                start_time=int(row['start_time'])
                timestamps=[int(start_time)] + [int(start_time)+ int(ct) for ct in cum_time]
                this_trip={'path': coords, 'timestamps': timestamps}
                if self.mode_descriptions is not None:
                    this_trip['mode']=mode_id_map[row['mode']]
                if self.profile_descriptions is not None:
                    this_trip['profile']=profile_id_map[row['earnings']]
                trips.append(this_trip)
        return {'attr': legend, 'trips': trips}
    
    def get_edge_traversals(self, route_table):
        """
        Create a table with a row for every time someone travserses a link
        Include edge identifier, from coordinate, to coordinate and personal attributes
        """
        route_table['n_edges']=route_table.apply(lambda row: len(row['attributes']['edges']), axis=1)
        edge_traversal={'edge_id': [], 'from_coord': [], 'to_coord': []}
        for ind, row in route_table.iterrows():
            edge_traversal['edge_id'].extend(row['attributes']['edges'].copy())
            route_coords=row['attributes']['coordinates'].copy()
            edge_traversal['from_coord'].extend(route_coords[:-1])
            edge_traversal['to_coord'].extend(route_coords[1:])
        # person-level attributes- replicated for each edge in the route
        for p_attr in (self.person_attributes+['start_time', 'mode']):
            attr_as_list=list(route_table[p_attr])
            n_edges_by_route=list(route_table['n_edges'])
            this_attribute_by_edge=[]
            for t in range(len(attr_as_list)):
                this_attribute_by_edge.extend([attr_as_list[t]]*n_edges_by_route[t])
            edge_traversal[p_attr]=this_attribute_by_edge
        return pd.DataFrame(edge_traversal) 

    def get_node_traversals(self, route_table):
        route_table['n_nodes']=route_table.apply(lambda row: len(row['node_path']), axis=1)
        node_traversal={'coord': [], 'ts': [], 'node_id':[]}
        for ind, row in route_table.iterrows():
            mode_id=row['mode']
            target_network_id=self.mob_sys.modes[mode_id].target_network_id
            travel_time_metric=self.mob_sys.modes[mode_id].travel_time_metric
            if row['n_nodes']>1:
#                 print('{}_{}_{}'.format(i_r, len(route['coordinates']), len(node_paths[i_r])))
                node_traversal['coord'].extend(row['attributes']['coordinates'].copy())
                node_traversal['node_id'].extend(row['node_path'].copy())
                trip_start=int(row['start_time'])
                timestamps=[trip_start]+list((trip_start+np.cumsum(row['attributes'][travel_time_metric].copy())).astype(int))
                node_traversal['ts'].extend(timestamps)
        # person-level attributes- replicated for each edge in the route
        for p_attr in (self.person_attributes+['mode', 'person_id']):
            attr_as_list=list(route_table[p_attr])
            n_nodes_by_route=list(route_table['n_nodes'])
            this_attribute_by_node=[]
            for t in range(len(attr_as_list)):
                if n_nodes_by_route[t]>1:
                    this_attribute_by_node.extend([attr_as_list[t]]*n_nodes_by_route[t])
            node_traversal[p_attr]=this_attribute_by_node
#         for col in node_traversal:
#             print('{}_{}'.format(col, len(node_traversal[col])))
        return pd.DataFrame(node_traversal)  
    
    def get_edge_traffic(self, edge_traversal_table, mode):
        edge_traversal_table['count']=1
        agg_dict={'from_coord': lambda x: x.iloc[0],
                  'to_coord': lambda x: x.iloc[0],
                  'count': sum}
        agg_edge_traffic=edge_traversal_table.groupby('edge_id').agg(agg_dict)
        return agg_edge_traffic

        # if ((self.centre_x_y is not None) and (self.vis_radius is not None)):
        #     agg_edge_traffic['in_scope']=agg_edge_traffic.apply(lambda row:get_haversine_distance(
        #         row['from_coord'], self.centre_x_y)<self.vis_radius, axis=1)
        #     return agg_edge_traffic[agg_edge_traffic['in_scope']]
        # else:
        #     return agg_edge_traffic
        
    def node_traversal_to_trips_json(self, node_traversal_table):
#         if ((self.centre_x_y is not None) and (self.vis_radius is not None)):
# #             node_traversal_table['in_scope']=node_traversal_table.apply(lambda row:get_haversine_distance(
# #                 row['coord'], centre_x_y)<vis_radius, axis=1)           
# #             node_traversal_table=node_traversal_table[node_traversal_table['in_scope']]
#             for mode in node_traversal_table['mode'].unique():
#                 net=self.mob_sys.modes[mode].target_network_id
#                 node_traversal_table.loc[node_traversal_table['mode']==mode, 'in_scope'
#                                         ]=node_traversal_table.loc[node_traversal_table['mode']==mode, 'node_id'].isin(self.vis_nodes[net])                                        
        node_traversal_table['coord_ts']=node_traversal_table.apply(lambda row: row['coord']+[row['ts']], axis=1)
        agg_dict={'coord_ts': lambda x: list(x),
#                   'coord': lambda x: list(x),
#                   'ts': lambda x: list(x),
                  'age': lambda x: x.iloc[0],
                  'earnings': lambda x: x.iloc[0],
                  'industry': lambda x: x.iloc[0]}
        node_traversal_per_person_mode=node_traversal_table.groupby(['person_id', 'mode']).agg(agg_dict)
        trips=node_traversal_per_person_mode.to_dict(orient='records')
        return trips       
  
    def route_table_to_geo(self, route_table):    
        route_table['line_string']=route_table.apply(lambda row: 
            coord_list_to_line_string(row['attributes']['coordinates']), axis=1)
        route_gdf=gpd.GeoDataFrame(route_table, geometry='line_string')
        return route_gdf
    
    def route_gdf_to_trips_geojson(self, route_gdf, start_day_time_stamp):
        geo_dict=route_gdf.__geo_interface__
        for i_f, feat in enumerate(geo_dict['features']):
            if feat['geometry'] is not None:
                coordinates=feat['geometry']['coordinates']
                travel_time_metric=self.mob_sys.modes[feat['properties']['mode']].travel_time_metric
                timestamps=[feat['properties']['start_time']]+list(feat['properties']['start_time']+np.cumsum(feat['properties']['attributes'][travel_time_metric]))
                timestamps=[start_day_time_stamp+int(t) for t in timestamps]
                new_coordinates=[[c[0], c[1], 0, timestamps[i]] for i,c in enumerate(coordinates)]
                geo_dict['features'][i_f]['geometry']['coordinates']=new_coordinates
            del geo_dict['features'][i_f]['properties']['attributes']
            del geo_dict['features'][i_f]['properties']['node_path']    
        return geo_dict
                

    
        
        