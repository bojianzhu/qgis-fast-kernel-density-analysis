from .compute_kdv import  compute_kdv
from .utils import GPS_bound_to_XY, GPS_to_XY, XY_to_GPS, is_pandas_df, shift_GPS, shift_bound_GPS, shift_time, unshift_GPS,unshift_time
import pandas as pd
from io import StringIO
import os
from numpy import ndarray,array

class kdv:
    def __init__(self, data=None,GPS =True,KDV_type='KDV',bound=[],middle_lat=None,num_threads=8,
            row_pixels=800,col_pixels=640,bandwidth =1000,
            t_bound=[],t_pixels=32,bandwidth_t=6):
        '''
        bound = [X_L,X_U,Y_L,Y_U] or [Lon_L,Lon_U,Lat_L,Lat_U] (You can change it)
        GPS = True #using GPS coordinate 
        KDV_type="KDV","STKDV"
        num_threads=8 #The number of threads 
        row_pixels=800 #number of voxels in a row 
        col_pixels=640 #number of voxels in a column 
        kernel_s_type=1 #Epanechnikov kernel (Don't change it currently)
        bandwidth=1000 #Spatial bandwidth 
        t_L=0 #minimum time 
        t_U=100 #maximum time 
        t_pixels=32 #number of voxels in the time-axis 
        kernel_t_type=1 #Epanechnikov kernel (Don't change it currently) 
        bandwidth_t=6 #Temporal bandwidth 
        '''
        kernel_s_type = 1 
        kernel_t_type = 1
        self.GPS = GPS
        self.data = pd.DataFrame()
        self.bound = [0,0,0,0]
        self.t_bound = [0,0]
        self.KDV_type = KDV_type
        self.num_threads = num_threads
        self.row_pixels = row_pixels
        self.col_pixels = col_pixels
        self.kernel_s_type = kernel_s_type
        self.bandwidth = bandwidth
        self.t_pixels = t_pixels
        self.kernel_t_type = kernel_t_type
        self.bandwidth_t = bandwidth_t
        self.middle_lat = middle_lat
        self.omit_zero = 1
        self.set_data(data)
        self.set_bound(bound)
        if KDV_type != 'STKDV':
            KDV_type = 'KDV'
        if KDV_type =='STKDV':
            self.set_t_bound(t_bound)
            

    def set_data(self,data):
        if data is None:
            return
        if isinstance(data,(ndarray,list)):
            data = array(data)
            self.omit_zero = 0
            if len(data)<=3 :
                data = data.T
            _data = pd.DataFrame(data[:,:2],columns=['x','y'])
        elif not is_pandas_df(data):
            try:
                _data = pd.read_json(data)
            except:
                _data = pd.read_csv(data)
        else:
            _data = data.copy()

        if self.GPS:
            if self.middle_lat is None:
                if 'lat' not in _data:
                    self.middle_lat=90
                else:
                    self.middle_lat = min(_data['lat'])+max(_data['lat'])/2
            if 'lat' not in _data:
                XY_to_GPS(_data,self.middle_lat)
            else:
                GPS_to_XY(_data,self.middle_lat)


        self.min_x,self.min_y = shift_GPS(_data)
        
        if self.KDV_type =='STKDV':
            self.min_t = shift_time(_data)
        if 'w' not in _data:
            _data['w'] = 1
        self.data = _data
        if self.KDV_type == 'KDV':
            self.data_str = str(self.data[['x','y','w']].to_csv(index=False, float_format = '%.16f'))
        else:
            self.data_str = str(self.data[['x','y','t','w']].to_csv(index=False,float_format = '%.16f'))
        
    def set_bound(self,bound):
        try:
            if len(bound) !=4:
                bound = None
            if bound ==[0,0,0,0]:
                bound = None
        except:
            bound = None 
            
        if bound is None:
            bound = [min(self.data['x']), max(self.data['x']),min(self.data['y']),max(self.data['y'])]
        else:
            self.bound = bound
            bound = [bound[2],bound[3],bound[0],bound[1]]
            if self.GPS:
                #self.middle_lat = bound[2]+bound[3]//2
                GPS_bound_to_XY(bound,self.middle_lat)
                shift_bound_GPS(bound,self.min_x,self.min_y)
        self._bound = bound

    def set_t_bound(self,t_bound):
        try:
            if len(t_bound) !=2:
                t_bound = None
            if t_bound ==[0,0]:
                t_bound = None
        except:
            t_bound = None
        if t_bound is None:
            t_bound = [min(self.data['t']),max(self.data['t'])]
        else:
            t_bound[0] -= self.min_t
            t_bound[0] /= 86400
            t_bound[1] -= self.min_t
            t_bound[1] /= 86400
            
        self.t_bound =t_bound
        
    def set_args(self):
        self.args =[0,
            self.data_str,
            3 if self.KDV_type=='STKDV' else 1,
            self.num_threads,
            self._bound[0],
            self._bound[1],
            self._bound[2],
            self._bound[3],
            self.row_pixels,
            self.col_pixels,
            self.kernel_s_type,
            self.bandwidth,
            self.t_bound[0],
            self.t_bound[1],
            self.t_pixels,
            self.kernel_t_type,
            self.bandwidth_t,
            self.omit_zero,
        ]
        self.args = [str(x).encode('ascii') for x in self.args]
    
        
    def compute(self):
        self.set_args()
        kdv = compute_kdv(self.args)
        result = pd.read_csv(StringIO(kdv))
        unshift_GPS(result,self.min_x,self.min_y)
        if self.KDV_type == 'STKDV':
            unshift_time(result,self.min_t)
        if self.GPS:
            XY_to_GPS(result,self.middle_lat)
        
        if self.GPS:
            result_cols = ['lon','lat']
        else:
            result_cols = ['x','y']
        result_cols.append('val')
        
        if self.KDV_type =='STKDV':
            result_cols.append('t')
        self.result = result[result_cols]
        return self.result



        
