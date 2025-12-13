# -*- coding: utf-8 -*-
"""
NTKDV - Network Temporal Kernel Density Visualization

This class provides the Python interface for the NTKDV C++ algorithm.
"""

from .compute_ntkdv import compute_ntkdv
import time


class NTKDV:
    """
    Network Temporal Kernel Density Visualization class.
    
    This class extends NKDV with temporal analysis capabilities.
    
    Parameters:
        data_name (str): Path to the network data file
        out_name (str): Path for output file (optional)
        method (int): Algorithm method (1-4, default: 2)
            1: Basic NTKDV method
            2: Shortest path sharing method
            3: TIC (Temporal Interval Computation)
            4: TIS (Temporal Interval Sharing)
        lixel_reg_length (float): Lixel regular length in meters
        kernel_type (int): Kernel function type (default: 2 - Epanechnikov)
            Note: NTKDV only supports:
            2: Epanechnikov kernel
            3: Quartic kernel
        bandwidth_s (float): Spatial bandwidth in meters
        bandwidth_t (float): Temporal bandwidth in days
        timestamps (list): List of timestamp values for temporal analysis
    """
    
    def __init__(self, data_name=None, out_name=None, method=4, lixel_reg_length=1,
                 kernel_type=2, bandwidth_s=1000, bandwidth_t=6, timestamps=None):
        
        # method 3:TIC, 4:TIS
        self.data_name = data_name
        if out_name is None:
            self.out_name = 'results/%s_M%d_K%d' % (data_name, method, kernel_type)
        else:
            self.out_name = out_name
        self.method = method
        self.lixel_reg_length = lixel_reg_length
        self.kernel_type = kernel_type
        self.bandwidth_s = bandwidth_s
        self.bandwidth_t = bandwidth_t
        self.timestamps = timestamps if timestamps is not None else []
        self.result = None
    
    def set_data(self, data_name):
        """Set the network data file path."""
        self.data_name = data_name
    
    def set_timestamps(self, timestamps):
        """Set the timestamps for temporal analysis."""
        self.timestamps = timestamps
    
    def set_args(self):
        """Prepare arguments for the C++ library call."""
        # Arguments order:
        # 0: placeholder
        # 1: network_fileName
        # 2: out_NTKDV_fileName
        # 3: method
        # 4: lixel_reg_length
        # 5: kernel_type
        # 6: bandwidth_s
        # 7: bandwidth_t
        # 8: T (number of timestamps)
        # 9+: timestamp values
        self.args = [
            0,
            self.data_name,
            self.out_name,
            self.method,
            self.lixel_reg_length,
            self.kernel_type,
            self.bandwidth_s,
            self.bandwidth_t,
            len(self.timestamps)
        ]
        
        # Add timestamp values
        for ts in self.timestamps:
            self.args.append(ts)
        
        self.args = [str(x).encode('ascii') for x in self.args]
    
    def compute(self):
        """
        Execute the NTKDV computation.
        
        Returns:
            str: The result string containing KDE values for each lixel at each timestamp
        """
        if self.data_name is None:
            print('Please set data file with set_data')
            return ''
        if not self.timestamps:
            print('Please set timestamps with set_timestamps')
            return ''
        
        self.set_args()
        start_time = time.time()
        self.result = compute_ntkdv(self.args)
        self.compute_time = time.time() - start_time
        return self.result

