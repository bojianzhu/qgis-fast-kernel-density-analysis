from .compute_nkdv import compute_nkdv

class NKDV:
    def __init__(self, data_name=None,out_name =None,method=3,lixel_reg_length=1,kernel_type=2,bandwidth=1):
        self.data_name = data_name
        if out_name is None:
            self.out_name = 'results/%s_M%d_K%d'%(data_name, method, kernel_type)
        else:
            self.out_name = out_name
        self.method = method
        self.lixel_reg_length = lixel_reg_length
        self.kernel_type = kernel_type
        self.bandwidth = bandwidth
            
    def set_data(self,data_name):
        self.data_name=data_name
        # with open(self.data_name,'r') as f:
        #     self.data = f.readlines()
        pass
        
    def set_args(self):
        self.args =[
            0,
            self.data_name,
            self.out_name,
            self.method,
            self.lixel_reg_length,
            self.kernel_type,
            self.bandwidth
        ]
        
        self.args = [str(x).encode('ascii') for x in self.args]
    
        
    def compute(self):
        if self.data_name==None:
            print('Please set data file with set_data')
            return ''
        self.set_args()
        self.result = compute_nkdv(self.args)
        return self.result


