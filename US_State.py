import us
import math
import pandas as pd
import geopandas as gpd
import numpy as np
import urllib.request as ur
from gzip import GzipFile
import json

def get_haversine_distance(point_1, point_2):
    # TODO: vectorise for fast calculation of multiple queries
    """
    Calculate the distance between any 2 points on earth given as [lon, lat]
    """
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(math.radians, [point_1[0], point_1[1], 
                                                point_2[0], point_2[1]])
    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371000 # Radius of earth in kilometers. Use 3956 for miles
    return c * r
       
class US_State():
    def __init__(self, state_fips, year=2017, geom_type='block_group'):
        """
        geom_type should be one of ['block_group', 'block']
        """
        self.state_fips=str(state_fips).zfill(2)
        self.state=us.states.lookup(self.state_fips)
        self.geom_type=geom_type
        self.year=year
    def get_geometry(self, target_crs="EPSG:4326"):
        """
        if centre_lon_lat and radius are given, the returned geometry will be
        a subset of the zones in the state
        radius should be specified in meters
        """
        #TODO: look for saved geometry first
        print('Getting geometry ({}) for state: {}'.format(self.geom_type, self.state.name))
        if self.geom_type=='block_group':
            self.geom=gpd.read_file('https://www2.census.gov/geo/tiger/TIGER{}/BG/tl_{}_{}_bg.zip'.format(
                    self.year, self.year, self.state_fips))
            self.geom=self.geom.set_index('GEOID')
        elif self.geom_type=='block': 
            self.geom=gpd.read_file('https://www2.census.gov/geo/tiger/TIGER{}/TABBLOCK/tl_{}_{}_tabblock10.zip'.format(
                    self.year, self.year, self.state_fips))
            self.geom=self.geom.set_index('GEOID10')
        else:
            print('Unrecoginised geometry type: {}'.format(self.geom_type))
        self.geom=self.geom.to_crs(target_crs)
        centroids=self.geom['geometry'].centroid
        self.geom['x_centroid']=[c.x for c in centroids]
        self.geom['y_centroid']=[c.y for c in centroids]

    def subset_geom_by_distance(self, centre_x_y, radius, name):        
        print('\t Subsetting zones by distance')
        if self.geom.crs.axis_info[0] == 'metre':
            print('Warning: distance calculation with projected coordinate system untested')
            dist_from_centre=np.sqrt(np.power(self.geom['x_centroid']-centre_x_y[0], 2)+ 
                                     np.power(self.geom['y_centroid']-centre_x_y[1], 2))
        else:
            dist_from_centre=self.geom.apply(lambda row: get_haversine_distance(
                    [row['x_centroid'], row['y_centroid']], centre_x_y), axis=1)            
        self.geom[name]=dist_from_centre<=radius
                
    def get_bounds(self, subset_name=None):
        geom=self.return_geometry(subset_name)
        return geom.total_bounds
    
    def return_geometry(self, subset_name=None):
        if subset_name==None:
            return self.geom
        else:
            return self.geom.loc[self.geom[subset_name]]
                
    def get_lodes_data(self, include=['wac', 'rac', 'od']):
        if 'wac' in include:
            self.wac=self.get_wac_data()
        if 'rac' in include:
            self.rac=self.get_rac_data()  
        if 'od' in include:
            self.od=self.get_od_data()

            
    def get_od_data(self):
        print('Getting OD data from https://lehd.ces.census.gov/data/lodes/LODES7/')
        req = ur.Request('https://lehd.ces.census.gov/data/lodes/LODES7/{}/od/{}_od_main_JT00_{}.csv.gz'.format(
                self.state.abbr.lower(), self.state.abbr.lower(), self.year)) 
        z_f = ur.urlopen(req)
        f = GzipFile(fileobj=z_f, mode="r")
        od = pd.read_csv(f)
        print('\t Formatting OD data')
        od=self.format_lodes_data(od)
        return od

    def get_rac_data(self):
        print('Getting RAC data from https://lehd.ces.census.gov/data/lodes/LODES7/')
        req = ur.Request('https://lehd.ces.census.gov/data/lodes/LODES7/{}/rac/{}_rac_S000_JT00_{}.csv.gz'.format(
                self.state.abbr.lower(), self.state.abbr.lower(), self.year)) 
        z_f = ur.urlopen(req)
        f = GzipFile(fileobj=z_f, mode="r")
        rac = pd.read_csv(f)
        print('\t Formatting RAC data')
        rac=self.format_lodes_data(rac)
        return rac
    
    def get_wac_data(self):
        print('Getting WAC data from https://lehd.ces.census.gov/data/lodes/LODES7/')
        req = ur.Request('https://lehd.ces.census.gov/data/lodes/LODES7/{}/wac/{}_wac_S000_JT00_{}.csv.gz'.format(
                self.state.abbr.lower(), self.state.abbr.lower(), self.year)) 
        z_f = ur.urlopen(req)
        f = GzipFile(fileobj=z_f, mode="r")
        wac = pd.read_csv(f)
        print('\t Formatting WAC data')
        wac=self.format_lodes_data(wac)
        return wac
        
    def format_block_id(self, block_id):
        return str(int(block_id)).zfill(15)

    def format_block_group_id(self, block_id):
        return str(int(block_id)).zfill(12)
        
    def format_lodes_data(self, block_df):
        block_cols=[c for c in ['h_geocode', 'w_geocode'] if c in block_df.columns]

        if self.geom_type=='block':
            # use the existing geoid, just format and rename it
            for col in block_cols:
                block_df[col]=block_df.apply(lambda row: self.format_block_id(row[col]), axis=1)
            cols_to_rename={col: col.replace('geocode', 'geoid') for col in block_cols}
            block_df=block_df.rename(columns=cols_to_rename)
            block_df=block_df.set_index(list(cols_to_rename.values()), drop=False)
            return block_df
        elif self.geom_type=='block_group':
            # aggregate blocks to block groups
            cols_not_to_sum=block_cols +['createdate']
            block_group_cols=[]
            for col in block_cols:
                new_bg_col=col.split('_')[0]+'_geoid'
                cols_not_to_sum.append(new_bg_col)
                block_df[new_bg_col]=block_df[col].floordiv(1e3)
                # block_df[new_bg_col]=block_df.apply(lambda row: row[col][0:12], axis=1)
                block_group_cols.append(new_bg_col)
            cols_to_sum=[col for col in block_df.columns if not col in cols_not_to_sum]
            bg_df=block_df.groupby(block_group_cols, as_index=False)[cols_to_sum].agg('sum')
            for col in block_group_cols:
            	bg_df[col]=bg_df.apply(lambda row: self.format_block_group_id(row[col]), axis=1)
            bg_df=bg_df.set_index(block_group_cols, drop=False)
            return bg_df
        else:
            print('Geometry {} not recognised'.format(self.geom_type))

    def remove_non_urban_zones(self):
        # TODO maybe faster to check centroids
        print('Subsetting by urbanized areas')
        save_loc='./data/states/{}/'.format(self.state_fips)
        save_address=save_loc+'urbanized_geoids_{}.json'.format(self.geom_type)
        try:
            urbanized_geoids=json.load(open(save_address))
        except:
            ua=gpd.read_file('zip://./data/usa/tl_2017_us_uac10.zip')
            ua_state=ua.loc[ua['NAMELSAD10'].str.contains(' {}'.format(self.state.abbr))]
            urbanized=ua_state.loc[ua_state['UATYP10']=='U']
            urbanized = urbanized.to_crs("EPSG:4326")
            self.geom['copy_GEOID']=self.geom.index.copy()

            zone_intersect_ua=gpd.overlay(self.geom, urbanized, how='intersection')
            urbanized_geoids=zone_intersect_ua['copy_GEOID'].unique()
            if not os.path.isdir(save_loc):
                print('Creating directory for state {}'.format(self.state_fips))
                os.mkdir(save_loc)
            json.dump(urbanized_geoids.tolist(), open(save_address, 'w'))
        self.geom = self.geom.loc[urbanized_geoids]

    def add_lodes_cols_to_shape(self):
        rac_column_name_map={'C000': 'res_total',
        					'CE01': 'res_income_low',
        					'CE02': 'res_income_mid',
        					'CE03': 'res_income_high',
                             'CA01': 'res_age_low',
                             'CA02': 'res_age_mid',
                             'CA03': 'res_age_high',
                             'CD01': 'res_edu_no_highsch',
                             'CD02': 'res_edu_highsch',
                             'CD03': 'res_edu_some_college',
                             'CD04': 'res_edu_bach_or_higher'}
        wac_column_name_map={'C000': 'emp_total',
                			'CE01': 'emp_income_low',
        					'CE02': 'emp_income_mid',
        					'CE03': 'emp_income_high',
                             'CA01': 'emp_age_low',
                             'CA02': 'emp_age_mid',
                             'CA03': 'emp_age_high',
                             'CD01': 'emp_edu_no_highsch',
                             'CD02': 'emp_edu_highsch',
                             'CD03': 'emp_edu_some_college',
                             'CD04': 'emp_edu_bach_or_higher',
                             'CNS01': 'emp_naics_11',
                             'CNS02': 'emp_naics_21',
                             'CNS03': 'emp_naics_22',
                             'CNS04': 'emp_naics_23',
                             'CNS05': 'emp_naics_31-33',
                             'CNS06': 'emp_naics_42',
                             'CNS07': 'emp_naics_44-45',
                             'CNS08': 'emp_naics_48-49',
                             'CNS09': 'emp_naics_51',
                             'CNS10': 'emp_naics_52',
                             'CNS11': 'emp_naics_53',
                             'CNS12': 'emp_naics_54',
                             'CNS13': 'emp_naics_55',
                             'CNS14': 'emp_naics_56',
                             'CNS15': 'emp_naics_61',
                             'CNS16': 'emp_naics_62',
                             'CNS17': 'emp_naics_71',
                             'CNS18': 'emp_naics_72',
                             'CNS19': 'emp_naics_81',
                             'CNS20': 'emp_naics_92',
                             # 'CFS01': 'emp_prv_firm_size_u19',
                             # 'CFS02': 'emp_prv_firm_size_20-49',
                             # 'CFS03': 'emp_prv_firm_size_50-249',
                             # 'CFS04': 'emp_prv_firm_size_250-499',
                             # 'CFS05': 'emp_prv_firm_size_500+',
                             # 'CFA01': 'emp_prv_firm_age_0-1',
                             # 'CFA02': 'emp_prv_firm_age_2-3',
                             # 'CFA03': 'emp_prv_firm_age_4-5',
                             # 'CFA04': 'emp_prv_firm_age_6-10',
                             # 'CFA05': 'emp_prv_firm_age_11+'
                             }
        self.geom=self.geom.merge(self.rac[rac_column_name_map.keys()],how='left',
            left_index=True, right_index=True).rename(columns=rac_column_name_map)
        self.geom=self.geom.merge(self.wac[wac_column_name_map.keys()],how='left',
            left_index=True, right_index=True).rename(columns=wac_column_name_map)
        self.geom=self.geom.fillna(0)
            
    def lodes_to_pop_table(self, model_subset_name=None, sim_subset_name=None):
        """
        People who will be included in the simpop:
        - live AND work in the model area 
        - live OR work in the sim area
        """
        od_subset=self.od
        if model_subset_name is not None:
            included_geoids=list(self.return_geometry(model_subset_name).index)
            od_subset=od_subset.loc[((od_subset['h_geoid'].isin(included_geoids))&
                                 (od_subset['w_geoid'].isin(included_geoids)))]
        if sim_subset_name is not None:
            included_geoids=list(self.return_geometry(sim_subset_name).index)
            od_subset=od_subset.loc[((od_subset['h_geoid'].isin(included_geoids))|
                                 (od_subset['w_geoid'].isin(included_geoids)))]

        print('Using {} of {} rows in OD data'.format(len(od_subset), len(self.od)))
        # convert counts by attribute to probabilities for each attribute
        attr_cols=['S000', 'SA01', 'SA02', 'SA03', 'SE01', 'SE02','SE03', 'SI01', 'SI02', 'SI03']
        probs_all=od_subset[attr_cols].div(od_subset.S000, axis=0)
        probs_all=probs_all.rename(columns={col: 'prob_'+col for col in attr_cols})
        od_subset_probs=pd.concat([od_subset, probs_all], axis=1)
#        for each row, sample the appropriate number of people
        sampled_age, sampled_earning, sampled_industry, sampled_home, sampled_work= [], [],[],[],[]
        count=0
        for ind, row in od_subset_probs.iterrows():
            if count%10000==0:
                print('{} of {}'.format(count, len(od_subset_probs)))
            count+=1
            n=row['S000']
            age_samples=np.random.choice(a=['low','mid','high'], size=n, 
                                         p=row[['prob_SA01','prob_SA02','prob_SA03']])
            earn_samples=np.random.choice(a=['low','mid','high'], size=n, 
                                          p=row[['prob_SE01','prob_SE02','prob_SE03']])
            indust_samples=np.random.choice(a=['goods_prod','trade_trans_util','other'], 
                                            size=n, p=row[['prob_SI01','prob_SI02','prob_SI03']])
        #     sampled_persons=np.column_stack([age_samples, earn_samples, indust_samples, 
        #                                      [row['h_geoid']]*n, [row['w_geoid']]*n ])
            sampled_age.extend(age_samples)
            sampled_earning.extend(earn_samples)
            sampled_industry.extend(indust_samples)
            sampled_home.extend([row['h_geoid']]*n)
            sampled_work.extend([row['w_geoid']]*n)
        return pd.DataFrame.from_dict({'age':sampled_age, 'earnings': sampled_earning, 'industry': sampled_industry, 'home_geoid': sampled_home,
                                                   'work_geoid': sampled_work}, orient='columns')