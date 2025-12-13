# -*- coding: utf-8 -*-

"""
/***************************************************************************
 Fast Density Analysis
                                 A QGIS plugin
 A fast kernel density visualization plugin for geospatial analytics
 ***************************************************************************/
"""

__author__ = 'LibKDV Group'
__date__ = '2023-07-03'
__copyright__ = '(C) 2023 by LibKDV Group'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

import os
from .utils.overpass import *
from .utils import osmnx as ox
from .network_cache import NetworkCache, download_and_cache_network
import processing
import pandas as pd
from io import StringIO
from .ntkdv import NTKDV
import networkx as nx
import numpy as np
from shapely.geometry import Point
import geopandas as gpd
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsMessageLog,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFolderDestination,
    QgsCoordinateReferenceSystem,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterDefinition,
    QgsClassificationQuantile,
    QgsVectorLayer,
    QgsProject,
    QgsStyle,
    QgsGraduatedSymbolRenderer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterField,
    QgsProcessingParameterDateTime,
    QgsProcessingParameterEnum,
    QgsLineSymbol,
    Qgis
)
import time
from datetime import datetime
# =============================================================================
# DEBUG SETTINGS - Change these for debugging
# =============================================================================
# Set to True to print detailed debug messages
DEBUG_MODE = False
# =============================================================================

def update_length(df1, df2):
    """Update length column in df1 with values from df2."""
    df1['length'] = df2['length']


def add_kd_value(gdf, value_se):
    """Add kernel density value column to GeoDataFrame."""
    columns_list = gdf.columns.tolist()
    columns_list.append('value')
    gdf = gdf.reindex(columns=columns_list)
    gdf['value'] = value_se
    return gdf


def merge(edges_df, dis_df, nodes_num, folder_path):
    """Merge edge and distance dataframes and write to graph_output file."""
    merge_df = pd.merge(edges_df, dis_df, on=['u_id', 'v_id'], how='left')
    merge_df = merge_df.sort_values(by=['u_id', 'v_id'], ascending=[True, True])
    merge_df = merge_df.reset_index()
    merge_np = merge_df.to_numpy()
    
    if np.isnan(merge_np[0][4]):
        row = [merge_np[0][1], merge_np[0][2], merge_np[0][3], 0]
    else:
        row = [merge_np[0][1], merge_np[0][2], merge_np[0][3], 1, merge_np[0][4], merge_np[0][5]]
    
    res = []
    for i in range(1, merge_np.shape[0]):
        if merge_np[i][1] == merge_np[i - 1][1] and merge_np[i][2] == merge_np[i - 1][2]:
            row[3] = row[3] + 1
            row.append(merge_np[i][4])
            row.append(merge_np[i][5])
        elif np.isnan(merge_np[i][4]):
            res.append(row)
            row = [merge_np[i][1], merge_np[i][2], merge_np[i][3], 0]
        else:
            res.append(row)
            row = [merge_np[i][1], merge_np[i][2], merge_np[i][3], 1, merge_np[i][4], merge_np[i][5]]
    res.append(row)
    
    with open(folder_path + '/graph_output', 'w') as fp:
        fp.write("%s " % str(nodes_num))
        fp.write("%s\n" % str(edges_df.shape[0]))
        for list_in in res:
            fp.write("%s " % str(int(list_in[0])))
            fp.write("%s" % str(int(list_in[1])))
            for i in range(2, len(list_in)):
                fp.write(" %s" % str(list_in[i]))
            fp.write("\n")


def project_data_points_and_generate_points_layer(graph, nodes, timestamps, folder_path, feedback):
    """Project data points onto the road network and return distances with timestamps."""
    longitudes = nodes[:, 0]
    latitudes = nodes[:, 1]
    points_list = [Point((lon, lat)) for lon, lat in zip(longitudes, latitudes)]
    points = gpd.GeoSeries(points_list, crs='epsg:4326')
    points_proj = points.to_crs(graph.graph['crs'])
    xs = [pp.x for pp in points_proj]
    ys = [pp.y for pp in points_proj]
    nearest_edges = ox.nearest_edges(graph, xs, ys)
    distances = []

    for i in range(len(longitudes)):
        if i % 10000 == 0:
            pass

        point1_id = nearest_edges[i][0]
        point2_id = nearest_edges[i][1]

        data_point = Point(xs[i], ys[i])
        edge = graph.get_edge_data(nearest_edges[i][0], nearest_edges[i][1])[0]['geometry']
        projected_dist = edge.project(data_point)

        distances.append([point1_id, point2_id, projected_dist, timestamps[i]])

    distances_df = pd.DataFrame(distances, columns=['u_id', 'v_id', 'distance', 'time'])
    distances_df = distances_df.sort_values(
        by=['u_id', 'v_id', 'distance'],
        ascending=[True, True, True],
        ignore_index=True
    )
    return distances_df


def fix_direction(graph):
    """Fix edge direction to ensure geometry starts from source node."""
    x_dic = {}
    for i, node in enumerate(graph.nodes(data=True)):
        x_dic[i] = node[1]['x']
    for i, edge in enumerate(graph.edges(data=True)):
        shapely_geometry = edge[2]['geometry']
        x, y = shapely_geometry.xy
        if abs(x[0] - x_dic[edge[0]]) > 0.00001:
            edge[2]['geometry'] = shapely_geometry.reverse()


def process_edges(graph):
    """Process graph edges into a DataFrame."""
    edge_list = []
    for edge in graph.edges:
        node1_id = edge[0]
        node2_id = edge[1]
        length = graph[node1_id][node2_id][0]['length']
        edge_list.append([node1_id, node2_id, length])
    return pd.DataFrame(edge_list, columns=['u_id', 'v_id', 'length'])


class NTKDVAlgorithm(QgsProcessingAlgorithm):
    """
    Network Temporal Kernel Density Visualization (NTKDV) Algorithm.
    
    This algorithm extends NKDV with temporal analysis capabilities,
    producing density maps for multiple time slices.
    """

    OUTPUT = 'OUTPUT'
    INPUT = 'INPUT'
    TIMEFIELD = 'TIMEFIELD'
    BANDWIDTH_S = 'BANDWIDTH_S'
    BANDWIDTH_T = 'BANDWIDTH_T'
    LIXEL_LENGTH = 'LIXEL_LENGTH'
    KERNEL_TYPE = 'KERNEL_TYPE'
    TIMESTAMP_MODE = 'TIMESTAMP_MODE'
    TIMEAXIS = 'TIMEAXIS'
    STARTTIME = 'STARTTIME'
    ENDTIME = 'ENDTIME'
    FOLDER_PATH = 'FOLDER_PATH'
    
    # Kernel type options for NTKDV: only Epanechnikov and Quartic are supported
    # Index 0 -> k_type 2 (Epanechnikov), Index 1 -> k_type 3 (Quartic)
    KERNEL_OPTIONS = ['Epanechnikov', 'Quartic']
    KERNEL_TYPE_MAP = {0: 2, 1: 3}  # Map selection index to actual k_type value
    
    # Timestamp mode options
    TIMESTAMP_MODE_OPTIONS = ['Auto (uniform intervals)', 'Manual (specify dates)']

    def initAlgorithm(self, config):
        """Initialize algorithm parameters."""
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Input point layer'),
                [QgsProcessing.TypeVectorPoint]
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.FOLDER_PATH,
                self.tr('Cache folder')
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.TIMEFIELD,
                self.tr('Time field'),
                None,
                self.INPUT
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.BANDWIDTH_S,
                'Spatial bandwidth (meters)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=500
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.BANDWIDTH_T,
                'Temporal bandwidth (days)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=6
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LIXEL_LENGTH,
                'Lixel size (meters)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=20
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.KERNEL_TYPE,
                'Kernel type',
                options=self.KERNEL_OPTIONS,
                defaultValue=0,  # Epanechnikov as default
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.TIMESTAMP_MODE,
                'Timestamp mode',
                options=self.TIMESTAMP_MODE_OPTIONS,
                defaultValue=0,  # Auto mode as default
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TIMEAXIS,
                'Time-axis (number of time slices) [Auto mode only]',
                type=QgsProcessingParameterNumber.Integer,
                minValue=1,
                defaultValue=8,
                optional=True
            )
        )
        # Note: Start/End time are now auto-detected from data (min/max time)
        # These parameters are kept for backward compatibility but are optional
        param = QgsProcessingParameterDateTime(
            self.STARTTIME,
            'Start time (optional, auto-detect from data if not set)',
            optional=True
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        param = QgsProcessingParameterDateTime(
            self.ENDTIME,
            'End time (optional, auto-detect from data if not set)',
            optional=True
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        # Manual date parameters - up to 10 dates with date picker (folded under Advanced)
        for i in range(1, 11):
            param = QgsProcessingParameterDateTime(
                f'MANUAL_DATE_{i}',
                f'[Manual mode] Date {i}',
                optional=True
            )
            param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
            self.addParameter(param)
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                self.tr('Output File'),
                fileFilter='GeoPackage (*.gpkg *.GPKG);;ESRI Shapefile (*.shp *.SHP)'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """Execute the NTKDV algorithm."""
        self.folder_path = self.parameterAsFileOutput(parameters, self.FOLDER_PATH, context)
        bandwidth_s = self.parameterAsDouble(parameters, self.BANDWIDTH_S, context)
        bandwidth_t = self.parameterAsDouble(parameters, self.BANDWIDTH_T, context)
        lixel_length = self.parameterAsDouble(parameters, self.LIXEL_LENGTH, context)
        kernel_type_idx = self.parameterAsEnum(parameters, self.KERNEL_TYPE, context)
        kernel_type = self.KERNEL_TYPE_MAP[kernel_type_idx]  # Map to actual k_type value (2 or 3)
        timestamp_mode = self.parameterAsEnum(parameters, self.TIMESTAMP_MODE, context)
        source = self.parameterAsSource(parameters, self.INPUT, context)
        fld_time = self.parameterAsString(parameters, self.TIMEFIELD, context)

        input_layer_name = source.sourceName()
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        # Add coordinate fields
        add_coor_layer = processing.run(
            "native:addxyfields",
            {
                'INPUT': parameters['INPUT'],
                'CRS': QgsCoordinateReferenceSystem('EPSG:4326'),
                'PREFIX': 'ntkdv_',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
        )['OUTPUT']

        add_coor_source = self.parameterAsSource(
            {'INPUT': add_coor_layer, 'OUTPUT': ''},
            self.INPUT,
            context
        )

        # Process based on timestamp mode
        if timestamp_mode == 0:  # Auto mode
            feedback.pushInfo('Using Auto timestamp mode (uniform intervals)')
            t_pixels = self.parameterAsInt(parameters, self.TIMEAXIS, context)
            
            # First pass: collect ALL data points and find time range
            coor_list = []
            raw_time_list = []
            for current, f in enumerate(add_coor_source.getFeatures()):
                t_value = f[fld_time]
                coor_list.append([f['ntkdv_x'], f['ntkdv_y']])
                raw_time_list.append(t_value)

            if not coor_list:
                feedback.pushInfo('No data points found.')
                return {self.OUTPUT: None}

            # Auto-detect time range from data (min/max)
            min_t = min(raw_time_list)
            max_t = max(raw_time_list)
            
            # Check if user provided custom time range (optional override)
            start_time = self.parameterAsDateTime(parameters, self.STARTTIME, context)
            end_time = self.parameterAsDateTime(parameters, self.ENDTIME, context)
            
            if start_time and start_time.isValid():
                st = datetime.strptime(start_time.toString("yyyy-MM-dd hh:mm:ss"), '%Y-%m-%d %H:%M:%S').timestamp()
                feedback.pushInfo(f'Using custom start time: {start_time.toString("yyyy-MM-dd hh:mm:ss")}')
            else:
                st = min_t
                feedback.pushInfo('Start time: {}'.format(datetime.fromtimestamp(st).strftime("%Y-%m-%d %H:%M:%S")))
            
            if end_time and end_time.isValid():
                et = datetime.strptime(end_time.toString("yyyy-MM-dd hh:mm:ss"), '%Y-%m-%d %H:%M:%S').timestamp()
                feedback.pushInfo(f'Using custom end time: {end_time.toString("yyyy-MM-dd hh:mm:ss")}')
            else:
                et = max_t
                feedback.pushInfo('End time: {}'.format(datetime.fromtimestamp(et).strftime("%Y-%m-%d %H:%M:%S")))
            
            if DEBUG_MODE:
                feedback.pushInfo('[DEBUG] Time range: {} to {}'.format(
                    datetime.fromtimestamp(st).strftime("%Y-%m-%d %H:%M:%S"),
                    datetime.fromtimestamp(et).strftime("%Y-%m-%d %H:%M:%S")
                ))
            
            feedback.pushInfo(f'  Duration: {(et - st) / 86400.0:.2f} days')

            # Filter data points within time range (if custom range specified)
            if st != min_t or et != max_t:
                filtered_coor = []
                filtered_time = []
                for i, t in enumerate(raw_time_list):
                    if st <= t <= et:
                        filtered_coor.append(coor_list[i])
                        filtered_time.append(t)
                coor_list = filtered_coor
                raw_time_list = filtered_time
                min_t = min(raw_time_list) if raw_time_list else st
                if DEBUG_MODE:
                    feedback.pushInfo(f'[DEBUG] Filtered to {len(coor_list)} points within time range')

            # Convert to days relative to min_t
            time_list = [(t - min_t) / 86400.0 for t in raw_time_list]

            # Calculate uniform timestamp values (relative to min_t)
            time_interval = (et - st) / t_pixels
            timestamps = []
            timestamp_datetimes = []
            for t in range(t_pixels):
                cur_time = st + t * time_interval
                next_time = st + (t + 1) * time_interval
                middle_time = (cur_time + next_time) / 2.0
                # Convert to days relative to min_t
                timestamps.append((middle_time - min_t) / 86400.0)
                timestamp_datetimes.append(datetime.fromtimestamp(middle_time))
            
            feedback.pushInfo('Generated {} timestamps (relative to start time):'.format(len(timestamps)))
            for i, dt in enumerate(timestamp_datetimes):
                feedback.pushInfo('  [{}] {} (day {:.2f})'.format(i, dt.strftime("%Y-%m-%d %H:%M:%S"), timestamps[i]))

        else:  # Manual mode
            feedback.pushInfo('Using Manual timestamp mode')
            
            # Collect manual dates from DateTime parameters
            timestamp_datetimes = []
            for i in range(1, 11):
                param_name = f'MANUAL_DATE_{i}'
                date_value = self.parameterAsDateTime(parameters, param_name, context)
                if date_value and date_value.isValid():
                    date_str = date_value.toString("yyyy-MM-dd hh:mm:ss")
                    dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                    timestamp_datetimes.append(dt)
            
            if not timestamp_datetimes:
                feedback.pushInfo('Error: Manual mode requires at least one date.')
                return {self.OUTPUT: None}

            # Sort timestamps
            timestamp_datetimes.sort()

            # First pass: collect all data points and find min_t
            coor_list = []
            raw_time_list = []
            
            for current, f in enumerate(add_coor_source.getFeatures()):
                t_value = f[fld_time]
                coor_list.append([f['ntkdv_x'], f['ntkdv_y']])
                raw_time_list.append(t_value)

            if not coor_list:
                feedback.pushInfo('No data points found.')
                return {self.OUTPUT: None}

            # Find min_t from the data
            min_t = min(raw_time_list)
            feedback.pushInfo('Data time range: {} to {}'.format(
                datetime.fromtimestamp(min(raw_time_list)).strftime("%Y-%m-%d %H:%M:%S"),
                datetime.fromtimestamp(max(raw_time_list)).strftime("%Y-%m-%d %H:%M:%S")
            ))

            # Convert to days relative to min_t
            time_list = [(t - min_t) / 86400.0 for t in raw_time_list]

            # Convert manual timestamps to days relative to min_t
            timestamps = [(dt.timestamp() - min_t) / 86400.0 for dt in timestamp_datetimes]
            
            feedback.pushInfo('Using {} manual timestamps (relative to start date):'.format(len(timestamps)))
            for i, dt in enumerate(timestamp_datetimes):
                feedback.pushInfo('  [{}] {} (day {:.2f})'.format(i, dt.strftime("%Y-%m-%d %H:%M:%S"), timestamps[i]))

        result_layers = self.run_ntkdv(
            coor_list=coor_list,
            time_list=time_list,
            timestamps=timestamps,
            timestamp_datetimes=timestamp_datetimes,
            context=context,
            bandwidth_s=bandwidth_s,
            bandwidth_t=bandwidth_t,
            lixel_length=lixel_length,
            kernel_type=kernel_type,
            path=output_path,
            input_layer_name=input_layer_name,
            feedback=feedback,
            min_t=min_t
        )

        return {self.OUTPUT: result_layers}

    def run_ntkdv(self, path, coor_list, time_list, timestamps, timestamp_datetimes, context, input_layer_name, 
                  feedback, bandwidth_s=1000, bandwidth_t=6, lixel_length=5, kernel_type=2, min_t=0):
        """Execute the NTKDV computation and generate output layers."""
        data_df = pd.DataFrame(coor_list, columns=['lon', 'lat'])
        lat_max = data_df['lat'].max()
        lat_min = data_df['lat'].min()
        lon_max = data_df['lon'].max()
        lon_min = data_df['lon'].min()

        # Start loading road network (with automatic caching)
        feedback.pushInfo('Start loading road network')
        start = time.time()
        
        g, xml_path, from_cache = download_and_cache_network(
            lat_min, lat_max, lon_min, lon_max,
            self.folder_path, feedback
        )

        nodes_num = g.number_of_nodes()
        fix_direction(g)
        end = time.time()
        duration = end - start
        feedback.pushInfo('End loading road network, duration:{}s'.format(duration))

        # Start processing edges
        if DEBUG_MODE:
            feedback.pushInfo('[DEBUG] Start processing edges')
        start = time.time()
        edge_df = process_edges(g)
        geo_path_1 = self.folder_path + '/geo1.gpkg'
        ox.save_graph_geopackage(g, geo_path_1)
        df1 = gpd.read_file(geo_path_1, layer='edges')
        geo_path_2 = self.folder_path + '/simplified.gpkg'
        df1 = df1[['geometry']]
        df1.to_file(geo_path_2, driver='GPKG', layer='edges')

        add_geometry_2 = processing.run(
            "qgis:exportaddgeometrycolumns",
            {
                'INPUT': geo_path_2 + '|layername=edges',
                'CALC_METHOD': 0,
                'OUTPUT': "TEMPORARY_OUTPUT"
            }
        )['OUTPUT']

        add_coor_source = self.parameterAsSource(
            {'INPUT': add_geometry_2, 'OUTPUT': ''},
            self.INPUT,
            context
        )
        length_list = []
        for current, f in enumerate(add_coor_source.getFeatures()):
            length_list.append([f['length']])

        df2 = pd.DataFrame(length_list, columns=['length'])
        update_length(edge_df, df2)
        end = time.time()
        duration = end - start
        if DEBUG_MODE:
            feedback.pushInfo('[DEBUG] End processing edges, duration:{}s'.format(duration))

        # Start projecting points to the road
        if DEBUG_MODE:
            feedback.pushInfo('[DEBUG] Start projecting points to the road')
        start = time.time()
        data_arr = np.array(coor_list)
        distance_df = project_data_points_and_generate_points_layer(
            g, data_arr, time_list, self.folder_path, feedback
        )
        merge(edge_df, distance_df, nodes_num, self.folder_path)
        end = time.time()
        duration = end - start
        if DEBUG_MODE:
            feedback.pushInfo('[DEBUG] End projecting points to the road, duration:{}s'.format(duration))

        # Start splitting roads
        if DEBUG_MODE:
            feedback.pushInfo('[DEBUG] Start splitting roads')
        start = time.time()
        qgis_split_output = self.folder_path + '/split_by_qgis.geojson'
        processing.run(
            "native:splitlinesbylength",
            {
                'INPUT': geo_path_2 + '|layername=edges',
                'LENGTH': lixel_length,
                'OUTPUT': qgis_split_output
            }
        )
        end = time.time()
        duration = end - start
        if DEBUG_MODE:
            feedback.pushInfo('[DEBUG] End splitting roads, duration:{}s'.format(duration))

        # Start processing NTKDV
        feedback.pushInfo('Start processing NTKDV')
        kernel_name = self.KERNEL_OPTIONS[kernel_type - 2]  # kernel_type is 2 or 3, map to index 0 or 1
        feedback.pushInfo('Using kernel type: {} ({})'.format(kernel_type, kernel_name))
        start = time.time()
        example = NTKDV(
            bandwidth_s=bandwidth_s,
            bandwidth_t=bandwidth_t,
            lixel_reg_length=lixel_length,
            kernel_type=kernel_type,
            method=4
        )
        example.set_data(self.folder_path + '/graph_output')
        example.set_timestamps(timestamps)
        example.compute()
        feedback.pushInfo('End NTKDV computation, duration: {:.2f}s'.format(example.compute_time))
        end = time.time()
        duration = end - start
        if DEBUG_MODE:
            feedback.pushInfo('[DEBUG] End processing NTKDV, duration:{}s'.format(duration))

        # Start presenting results
        feedback.pushInfo('Start presenting results')
        start = time.time()

        # Parse NTKDV result
        result_io = StringIO(example.result)
        lines = result_io.readlines()
        num_lixels = int(lines[0].strip())
        num_timestamps = int(lines[1].strip())

        # Read base geometry
        with open(qgis_split_output) as file:
            df_base = gpd.read_file(file)

        result_layers = []
        line_idx = 2

        for t in range(num_timestamps):
            timestamp_value = float(lines[line_idx].strip())
            line_idx += 1

            values = []
            for l in range(num_lixels):
                parts = lines[line_idx].strip().split()
                kde_value = float(parts[3])
                values.append(kde_value)
                line_idx += 1

            # Create a copy of the base geometry
            df_copy = df_base.copy()
            df_copy['value'] = values
            if 'fid' in df_copy.columns:
                df_copy.drop(columns='fid', inplace=True)
            
            # Convert to EPSG:4326 (WGS84) for correct display in QGIS
            # The calculation was done in UTM (meters), but display needs lat/lon
            if df_copy.crs is not None and df_copy.crs.to_epsg() != 4326:
                df_copy = df_copy.to_crs(epsg=4326)

            # Generate output file path for this timestamp
            base_path = os.path.splitext(path)[0]
            ext = os.path.splitext(path)[1]
            
            # Use the provided datetime for this timestamp
            actual_time = timestamp_datetimes[t]
            time_str = actual_time.strftime("%Y-%m-%d_%H-%M-%S")
            
            output_file = f"{base_path}_T{t}_{time_str}{ext}"
            df_copy.to_file(output_file)

            # Create and style layer
            kernel_short = kernel_name[:3].lower()  # e.g., 'epa' for Epanechnikov
            layer_name = f'ntkdv_b{int(bandwidth_s)}_t{int(bandwidth_t)}_k{kernel_short}_{input_layer_name}_{time_str}'
            
            # Styling
            ramp_name = 'Turbo'
            value_field = 'value'
            num_classes = 20

            classification_method = QgsClassificationQuantile()
            v_layer = QgsVectorLayer(output_file, layer_name, "ogr")

            classification_method.setLabelFormat("%1 - %2")
            classification_method.setLabelPrecision(2)
            classification_method.setLabelTrimTrailingZeroes(True)

            default_style = QgsStyle().defaultStyle()
            color_ramp = default_style.colorRamp(ramp_name)

            # Create a line symbol with desired width BEFORE creating renderer
            LINE_WIDTH = 0.65  # <-- Change this value to adjust line width (in millimeters)
            line_symbol = QgsLineSymbol.createSimple({'width': str(LINE_WIDTH)})
            
            renderer = QgsGraduatedSymbolRenderer(value_field, [])
            renderer.setSourceSymbol(line_symbol)  # Set the source symbol with width
            renderer.setClassificationMethod(classification_method)
            renderer.updateClasses(v_layer, num_classes)
            renderer.updateColorRamp(color_ramp)
            
            v_layer.setRenderer(renderer)
            v_layer.triggerRepaint()

            QgsProject.instance().addMapLayer(v_layer)
            result_layers.append(v_layer)

        end = time.time()
        duration = end - start
        feedback.pushInfo('End presenting results, duration:{}s'.format(duration))

        return result_layers

    def name(self):
        """Return the algorithm name."""
        return 'networktemporalkdv(NTKDV)'

    def displayName(self):
        """Return the translated algorithm name for display."""
        return self.tr("Network Temporal KDV (NTKDV)")

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return NTKDVAlgorithm()

    def helpUrl(self):
        return "https://github.com/edisonchan2013928/PyNKDV"

    def shortDescription(self):
        return "Efficient and accurate network temporal kernel density visualization."

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icons/ntkdv.png'))

