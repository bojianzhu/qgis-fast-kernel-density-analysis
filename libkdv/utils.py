pi = 3.14159265358979323846
earth_radius = 6371000
from math import cos
import csv
import json
import numpy as np
import pandas as pd


def GPS_bound_to_XY(bound,middle_lat):
    middle_lat *= pi/180
    bound[0] = earth_radius * bound[0] * pi/180 * cos(middle_lat)
    bound[1] = earth_radius * bound[1] * pi/180* cos(middle_lat)
    bound[2] = earth_radius * bound[2] * pi/180
    bound[3] = earth_radius * bound[3] * pi/180

def shift_bound_GPS(bound,min_x,min_y):
    bound[0]+= - min_x
    bound[1]+= - min_x
    bound[2]+= - min_y
    bound[3]+= - min_y

def GPS_to_XY(data,middle_lat):
    middle_lat *= pi/180
    data['x'] = earth_radius * data['lon']* pi/180 * cos(middle_lat)
    data['y'] = earth_radius * data['lat']*pi/180

def XY_to_GPS(result,middle_lat):
    middle_lat *= pi/180
    result['lon'] = (result['x']/(earth_radius*cos(middle_lat)))* (180/pi)
    result['lat'] = (result['y']/earth_radius) * (180/pi)

def shift_GPS(data):
    min_x = min(data['x'])
    data['x'] += -min_x
    min_y = min(data['y'])
    data['y'] += -min_y
    
    return min_x,min_y

def unshift_GPS(data,min_x,min_y):
    data['x'] += min_x
    data['y'] += min_y
    

def shift_time(data):
    if 't' not in data:
        return 0
    min_t = min(data['t'])
    data['t'] += -min_t
    data['t'] /= 86400
    return min_t

def unshift_time(data,min_t):
    if 't' not in data:
        return 0
    data['t'] *= 86400
    data['t'] += min_t
    data['t'] = data['t'].astype('int')

    
def read_csv(f,GPS,KDV_type):
    reader = csv.reader(f)
    dataset = []
    keys_list = reader.__next__()
    
    for i in range(len((keys_list))):
        dataset.append([])
        
    for row in reader:
        for i in range(len((keys_list))):
            dataset[i].append(float(row[i]))
    dataset =dataset
    data = {}
    if GPS:
        data['lon'] = dataset[0]
        data['lat'] = dataset[1]
    else:
        data['x'] = dataset[0]
        data['y'] = dataset[1]
    
    data['w'] = dataset[-1] if (len(dataset)-(1 if KDV_type==3 else 0) ==3) else [1]*len(dataset[0])
    
    return data
    
def to_json(data,KDV_type,value=False):
    json_str = ""
    json_str += "["
    for key in data:
        try:
            data[key] = data[key].tolist()
        except:
            pass
    if not value:
        for i in range(len(data['x'])):
            json_str += "{"
            json_str += '"x":%f,'%data['x'][i]
            json_str += '"y":%f,'%data['y'][i]
            if KDV_type == 3:
                json_str += '"t":%f'%data['t'][i]
            json_str += '"w":%f'%data['w'][i]
            json_str += "},\n"
        json_str += "]"
        
    else:
        for i in range(len(data['x'])):
            json_str += "{"
            json_str += '"lat":%f,'%data['lat'][i]
            json_str += '"lon":%f,'%data['lon'][i]
            if KDV_type == 3:
                json_str += '"t":%f'%data['t'][i]
            json_str += '"val":%f'%data['val'][i]
            json_str += "},\n"

        json_str = json_str[:-2]+"]"
    return json_str
    
    
def read_json(f,GPS,KDV_type):
    pass

def parse_result(kdv):
    kdv = kdv[1:-1]+','
    result = {'x':[],'y':[],'val':[]}
    for line in kdv.split('\n'):
        tmp = json.loads(line[:-1])
        for key in result.keys():
            result[key].append(tmp[key])
    return result


def filter_data(df,center,attr_name,tolerance):
    lat_name,lon_name,_ = attr_name
    return df[attr_name][(df[lat_name]>center[0]-tolerance) & (df[lat_name]<center[0]+tolerance) & (df[lon_name]>center[1]-tolerance) & (df[lon_name]<center[1]+tolerance)]
def convert_timestamp(df,time_name):
    df[time_name] =  pd.to_datetime(df[time_name])
    df[time_name] = df[time_name].values.astype('int64') // 10 ** 9
    return df
def gps_data_processing(df,center,attr_name_df,tolerance=2):
    attr_name = ['lat','lon','t']
    _df = df.copy()
    _df.fillna(0,inplace=True)
    _df = filter_data(_df,center,attr_name_df,tolerance)
    convert_timestamp(_df,attr_name_df[2])
    _df.columns = attr_name
    return _df

def is_pandas_df(obj):
    return obj.__class__.__module__ == "pandas.core.frame" and obj.to_records and obj.to_dict