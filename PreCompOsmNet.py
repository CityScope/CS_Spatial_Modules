import osmnx
import pandas as pd
import geopandas as gpd
"""
Need osmnx installed to import this module
"""

def simplify_network(G, tolerance=10):
    Gp=osmnx.projection.project_graph(G)
    # simplify
    G_simp=osmnx.simplification.consolidate_intersections(
            Gp, tolerance=tolerance, rebuild_graph=True, dead_ends=False, 
            reconnect_edges=True)
    print('\t Simplified from {} to {} edges and {} to {} nodes'.format(
        len(G.edges), len(G_simp.edges), len(G.nodes), len(G_simp.nodes)))
    # project back to WGS
    G_simp_wgs=osmnx.projection.project_graph(G_simp, to_crs='epsg:4326')
    return G_simp_wgs

def pre_compute_paths(G, weight_metric='travel_time', save_route_costs=False):
    print('\t Pre-computing paths')
    fw_pred, fw_dist=osmnx.graph.nx.floyd_warshall_predecessor_and_distance(
        G, weight=weight_metric)
    if save_route_costs:
        return fw_pred, fw_dist
    else:
        return fw_pred

def get_graph_buffered_to_hw_type(geom, external_hw_tags, network_type):
    for buffer in [i*200 for i in range(1, 10)]:
        print('Buffer : {}'.format(buffer))
        geom_projected=osmnx.projection.project_gdf(geom)
        geom_projected_buffered=geom_projected.unary_union.buffer(buffer)

        geom_projected_buffered_gdf=gpd.GeoDataFrame(geometry=[geom_projected_buffered], crs=geom_projected.crs)
        geom_wgs_buffered_gdf=geom_projected_buffered_gdf.to_crs(geom.crs) 

        G_temp=osmnx.graph.graph_from_polygon(geom_wgs_buffered_gdf.iloc[0]['geometry'], network_type=network_type)
        all_hw_tags=[e[2]['highway'] for e in G_temp.edges(data=True)]

        if any([tag in all_hw_tags for tag in external_hw_tags]):
            return G_temp
        print('Doesnt contain external link types')
    print('Warning: internal network will not connect to external network')
    return G_temp 

def create_2_scale_osmnx_network(sim_area_gdf, model_area_gdf, add_modes=[], osm_mode='drive', 
                               external_hw_tags=["motorway","motorway_link","trunk","trunk_link"]):
    """
    This function will create a single network using all driving links
    Network will composed of all links in the (buffered) sim area and 
    certain types of links in the external model area as defined in 'external_hw_tags'
    If modes other than driving will use this networ (eg. bicycles, motorbikes), they should be specified in add_modes
    add_modes is list of modes (excluding driving) of the form {'name': 'cycle', 'speed': 4800/3600}
    """
    print('getting internal roads')
    G_sim = get_graph_buffered_to_hw_type(sim_area_gdf, external_hw_tags, osm_mode)
    print('getting external roads')
    G_model=osmnx.graph_from_polygon(model_area_gdf.unary_union,
                             network_type=osm_mode, custom_filter='["highway"~"{}"]'.format('|'.join(external_hw_tags)))
    G_combined=osmnx.graph.nx.compose(G_model,G_sim)
    
    G_combined=osmnx.add_edge_speeds(G_combined)
    G_combined=simplify_network(G_combined)
    G_combined=osmnx.add_edge_travel_times(G_combined)
    for edge in list(G_combined.edges):
        G_combined.edges[edge]['travel_time_drive']=G_combined.edges[edge]['travel_time']
    for mode in add_modes:
        for edge in list(G_combined.edges):
            G_combined.edges[edge]['travel_time_{}'.format(mode['name'])]=G_combined.edges[edge]['length']/mode['speed']  
    G_combined=osmnx.utils_graph.get_undirected(G_combined)
    
    fw_all, route_lengths=pre_compute_paths(G_combined, 
                                            weight_metric='length',
                                            save_route_costs=True)
    pre_comp_net=PreCompOSMNet(G_combined, fw_all)
    networks={'drive': pre_comp_net}
    
    mode_dicts= {'drive': {'target_network_id': 'drive','travel_time_metric': 'travel_time_drive'}}
    for mode in add_modes:
        name=mode['name']
        # all use the 'driving' network but with differnt travel times
        mode_dicts[name]={'target_network_id': 'drive','travel_time_metric': 'travel_time_{}'.format(name)}    
    return networks, mode_dicts, route_lengths 

class PreCompOSMNet():
    def __init__(self, G, pred):
        """
        Takes as input an osmnx network object, with a 'speed kph' attribute already added
        On intialisation, generates predecessors
        """
        for i_e, edge in enumerate(list(G.edges)):
            G.edges[edge]['edge_id']=i_e
        self.G=G
        self.predecessors=pred
        
    # def pre_compute_paths(self, save_travel_time=False):
    #     print('\t Pre-computing paths')
    #     fw_pred, fw_dist=osmnx.graph.nx.floyd_warshall_predecessor_and_distance(
    #         self.G, weight='travel_time')
    #     self.predecessors=fw_pred
    #     if save_dist:
    #     	self.travel_times=fw_dist
        
    def shortest_paths(self, nodes_a, nodes_b, imp_name=None):
        paths=[]
        for i in range(len(nodes_a)):
            paths.append(osmnx.graph.nx.algorithms.shortest_paths.dense.reconstruct_path(
                nodes_a[i], nodes_b[i], self.predecessors))
        return paths
        
    def get_node_ids(self, x_col, y_col):
        return osmnx.distance.get_nearest_nodes(self.G, x_col, y_col, method='kdtree')

    def get_nodes_df(self):
        return pd.DataFrame(data=[{'x': self.G.nodes[n]["x"], 
                    'y': self.G.nodes[n]["y"], 
                    'id': n} for n in self.G.nodes]).set_index('id')

    def get_path_link_attributes(self, path, attribute_names=['travel_time']):
        # https://github.com/gboeing/osmnx/blob/master/osmnx/plot.py for actual edge geometries
        output={attr: [] for attr in attribute_names}
        if len(path)>1:
            coordinates=[]
            edges=[]
            for u, v in zip(path[:-1], path[1:]):
#                 edges.append((u,v))
                # if there are parallel edges, select the shortest in length
                data = min(self.G.get_edge_data(u, v).values(), key=lambda d: d["length"])
                edges.append(data['edge_id'])
                coordinates.append([
                    self.G.nodes[u]["x"], 
                    self.G.nodes[u]["y"]])
                for attr in attribute_names:
                    output[attr].append(data[attr])
            coordinates.append([
                self.G.nodes[path[-1]]["x"], 
                self.G.nodes[path[-1]]["y"]])
            output['coordinates']=coordinates
            output['edges']=edges
            return output
        else:
            output['coordinates']=[]
            output['edges']=[]
            return output
