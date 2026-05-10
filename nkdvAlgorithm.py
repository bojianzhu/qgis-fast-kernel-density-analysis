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
from .network_cache import NetworkCache, download_and_cache_network, load_edges_npz, save_edges_npz
import processing
import pandas as pd
from io import StringIO
from .nkdv import *
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
    QgsClassificationQuantile,
    QgsVectorLayer,
    QgsProject,
    QgsStyle,
    QgsGraduatedSymbolRenderer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsLineSymbol
    )
import time

# =============================================================================
# DEBUG SETTINGS - Change these for debugging
# =============================================================================
# Set to True to print detailed debug messages
DEBUG_MODE = False
# =============================================================================

def update_length(df1, df2):
    df1['length'] = df2['length']


def add_kd_value(gdf, value_se):
    columns_list = gdf.columns.tolist()
    columns_list.append('value')
    gdf = gdf.reindex(columns=columns_list)
    gdf['value'] = value_se
    return gdf


def merge(edges_df, dis_df, nodes_num, folder_path):
    # df1 is edge dataframe and df2 is distance dataframe
    merge_df = pd.merge(edges_df, dis_df, on=['u_id', 'v_id'], how='left')
    merge_df = merge_df.sort_values(by=['u_id', 'v_id'], ascending=[True, True])
    merge_df = merge_df.reset_index()
    merge_np = merge_df.to_numpy()
    if np.isnan(merge_np[0][4]):  # or we can use merge_np[0][4]>0
        row = [merge_np[0][1], merge_np[0][2], merge_np[0][3], 0]
    else:
        row = [merge_np[0][1], merge_np[0][2], merge_np[0][3], 1, merge_np[0][4]]
    res = []
    for i in range(1, merge_np.shape[0]):
        if merge_np[i][1] == merge_np[i - 1][1] and merge_np[i][2] == merge_np[i - 1][2]:
            row[3] = row[3] + 1
            row.append(merge_np[i][4])
        elif np.isnan(merge_np[i][4]):
            res.append(row)
            row = [merge_np[i][1], merge_np[i][2], merge_np[i][3], 0]
        else:
            res.append(row)
            row = [merge_np[i][1], merge_np[i][2], merge_np[i][3], 1, merge_np[i][4]]
    res.append(row)
    with open(folder_path + '/graph_output', 'w') as fp:
        fp.write("%s " % str(nodes_num))
        fp.write("%s\n" % str(edges_df.shape[0]))
        for list_in in res:
            fp.write("%s " % str(int(list_in[0])))
            fp.write("%s" % str(int(list_in[1])))
            for i in range(2, len(list_in)):
                # write each item on a new line
                fp.write(" %s" % str(list_in[i]))
            fp.write("\n")


def project_data_points_and_generate_points_layer(graph, nodes, folder_path, feedback):
    longitudes = nodes[:, 0]
    latitudes = nodes[:, 1]
    points_list = [Point((lon, lat)) for lon, lat in zip(longitudes, latitudes)]  # turn into shapely geometry
    points = gpd.GeoSeries(points_list,
                           crs='epsg:4326')  # turn into GeoSeries
    # points.to_file(folder_path + '/points_layer.gpkg')
    points_proj = points.to_crs(graph.graph['crs'])
    xs = [pp.x for pp in points_proj]
    ys = [pp.y for pp in points_proj]
    nearest_edges = ox.nearest_edges(graph, xs, ys)  # time-consuming
    distances = []
    # print(len(nearest_edges))
    # print(len(longitudes))
    # project data points respectively
    # projected_point_list = []

    for i in range(len(longitudes)):
        if i % 10000 == 0:
            pass
            # ("current point: ", i)

        point1_id = nearest_edges[i][0]  # the nearest edge's source node's node id
        point2_id = nearest_edges[i][1]  # the nearest edge's target node's node id

        # generate projection on nearest edge
        data_point = Point(xs[i], ys[i])  # one data point to be projected
        edge = graph.get_edge_data(nearest_edges[i][0], nearest_edges[i][1])[0]['geometry']
        projected_dist = edge.project(data_point)

        # projected_point = edge.interpolate(projected_dist)
        # projected_point_list.append(projected_point)

        distances.append([point1_id, point2_id, projected_dist])

    # points = gpd.GeoSeries(projected_point_list, crs=graph.graph['crs'])
    # print(graph.graph['crs'])
    # projected_points = points.to_crs(4326)
    # projected_points.to_file(folder_path + '/projected_points_layer.gpkg')

    distances_df = pd.DataFrame(distances, columns=['u_id', 'v_id', 'distance'])
    distances_df = distances_df.sort_values(by=['u_id', 'v_id', 'distance'], ascending=[True, True, True],
                                            ignore_index=True)
    return distances_df


def fix_direction(graph):
    x_dic = {}
    for i, node in enumerate(graph.nodes(data=True)):
        x_dic[i] = node[1]['x']
    for i, edge in enumerate(graph.edges(data=True)):
        shapely_geometry = edge[2]['geometry']
        x, y = shapely_geometry.xy
        if abs(x[0] - x_dic[edge[0]]) > 0.00001:  # edge0 is u (source ID)
            edge[2]['geometry'] = shapely_geometry.reverse()


def process_edges(graph):
    edge_list = []
    for edge in graph.edges:
        node1_id = edge[0]
        node2_id = edge[1]
        length = graph[node1_id][node2_id][0]['length']
        edge_list.append([node1_id, node2_id, length])
    return pd.DataFrame(edge_list, columns=['u_id', 'v_id', 'length'])


class NKDVAlgorithm(QgsProcessingAlgorithm):

    OUTPUT = 'OUTPUT'
    INPUT = 'INPUT'
    VALUE_FIELD = 'VALUE_FIELD'
    BANDWIDTH = 'BANDWIDTH'
    LIXEL_LENGTH = 'LIXEL_LENGTH'
    KERNEL_TYPE = 'KERNEL_TYPE'
    FOLDER_PATH = 'FOLDER_PATH'
    
    # Kernel type options: 0=Gaussian, 1=Triangular, 2=Epanechnikov, 3=Quartic
    KERNEL_OPTIONS = ['Gaussian', 'Triangular', 'Epanechnikov', 'Quartic']

    def initAlgorithm(self, config):
        # We add the input vector features source. It can have any kind of geometry.
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
        # self.addParameter(
        #     QgsProcessingParameterField(
        #         self.VALUE_FIELD,
        #         self.tr('Value Field'),
        #         parentLayerParameterName=self.INPUT,
        #         type=QgsProcessingParameterField.Numeric)
        # )
        #
        # self.addParameter(
        #     QgsProcessingParameterFileDestination(
        #         self.OUTPUT,
        #         self.tr('Output File'),
        #         'CSV files (*.csv)',
        #     )
        # )
        self.addParameter(
            QgsProcessingParameterNumber(self.BANDWIDTH, 'Bandwidth (meters)', type=QgsProcessingParameterNumber.Double,
                                         defaultValue=500))
        self.addParameter(
            QgsProcessingParameterNumber(self.LIXEL_LENGTH, 'Lixel size (meters)', type=QgsProcessingParameterNumber.Double,
                                         defaultValue=20))
        self.addParameter(
            QgsProcessingParameterEnum(
                self.KERNEL_TYPE,
                'Kernel type',
                options=self.KERNEL_OPTIONS,
                defaultValue=2,  # Epanechnikov as default
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                self.tr('Output File'),
                fileFilter='GeoPackage (*.gpkg *.GPKG);;ESRI Shapefile (*.shp *.SHP)'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        self.folder_path = self.parameterAsFileOutput(parameters, self.FOLDER_PATH, context)
        print(self.folder_path)
        bandwidth = self.parameterAsDouble(parameters, self.BANDWIDTH, context)
        lixel_length = self.parameterAsDouble(parameters, self.LIXEL_LENGTH, context)
        kernel_type = self.parameterAsEnum(parameters, self.KERNEL_TYPE, context)
        source = self.parameterAsSource(parameters, self.INPUT, context)

        input_layer_name = source.sourceName()
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        print(output_path)
        add_coor_layer = processing.run("native:addxyfields",
                                        {'INPUT': parameters['INPUT'], 'CRS': QgsCoordinateReferenceSystem('EPSG:4326'),
                                         'PREFIX': 'nkdv_', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
        # add_coor_layer = processing.run("qgis:exportaddgeometrycolumns", {'INPUT':parameters['INPUT'],'CALC_METHOD':0,'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
        # processing.run("native:savefeatures", {'INPUT':add_coor_layer,'OUTPUT':'/Users/patrick/Desktop/new_test1.csv','LAYER_NAME':'','DATASOURCE_OPTIONS':'','LAYER_OPTIONS':''})
        add_coor_source = self.parameterAsSource({'INPUT': add_coor_layer, 'OUTPUT': ''}, self.INPUT, context)
        coor_list = []
        # add_coor_source.fields().toList()
        for current, f in enumerate(add_coor_source.getFeatures()):
            coor_list.append([f['nkdv_x'], f['nkdv_y']])

        result_layer = self.run_nkdv(coor_list=coor_list, context=context, bandwidth=bandwidth,
                                     lixel_length=lixel_length, kernel_type=kernel_type, path=output_path, 
                                     input_layer_name=input_layer_name, feedback=feedback)

        # fieldnames = [field.name() for field in source.fields()]
        # # Compute the number of steps to display within the progress bar and
        # # get features from source
        # total = 100.0 / source.featureCount() if source.featureCount() else 0
        # features = source.getFeatures()
        #
        # with open(csv, 'w') as output_file:
        #     # write header
        #     line = ','.join(name for name in fieldnames) + '\n'
        #     output_file.write(line)
        #     for current, f in enumerate(features):
        #         # Stop the algorithm if cancel button has been clicked
        #         if feedback.isCanceled():
        #             break
        #
        #         # Add a feature in the sink
        #         line = ','.join(str(f[name]) for name in fieldnames) + '\n'
        #         output_file.write(line)
        #
        #         # Update the progress bar
        #         feedback.setProgress(int(current * total))
        return {self.OUTPUT: result_layer}

    def run_nkdv(self, path, coor_list, context, input_layer_name, feedback, bandwidth=1000, lixel_length=5, kernel_type=2):
        data_df = pd.DataFrame(coor_list, columns=['lon', 'lat'])
        lat_max = data_df['lat'].max()  # north
        lat_min = data_df['lat'].min()  # south
        lon_max = data_df['lon'].max()  # east
        lon_min = data_df['lon'].min()  # west

        # ====================================================================
        # Prepare road network (download + all preprocessing). All sub-steps
        # are cache-aware; each one prints a single concise line.
        # ====================================================================
        feedback.pushInfo('Start preparing road network')
        prep_start = time.time()

        # --- 1) Graph (download or cache) ---
        g, xml_path, from_cache, cache_id = download_and_cache_network(
            lat_min, lat_max, lon_min, lon_max,
            self.folder_path, feedback
        )
        nodes_num = g.number_of_nodes()
        nc = NetworkCache(feedback)
        preproc_paths = nc.get_preproc_paths(cache_id, lixel_length)
        fix_direction(g)  # always run; in-place

        # --- 2) Edges + simplified.gpkg (cache-aware) ---
        geo_path_2 = preproc_paths['simplified_gpkg']
        if nc.has_graph_preproc(cache_id):
            edge_df = load_edges_npz(preproc_paths['edges_npz'])
        else:
            edge_df = process_edges(g)
            geo_path_1 = self.folder_path + '/geo1.gpkg'
            ox.save_graph_geopackage(g, geo_path_1)
            df1 = gpd.read_file(geo_path_1, layer='edges')[['geometry']]
            if os.path.exists(geo_path_2):
                os.remove(geo_path_2)
            df1.to_file(geo_path_2, driver='GPKG', layer='edges')
            add_geometry_2 = processing.run("qgis:exportaddgeometrycolumns",
                                            {'INPUT': geo_path_2 + '|layername=edges', 'CALC_METHOD': 0,
                                             'OUTPUT': "TEMPORARY_OUTPUT"})['OUTPUT']
            add_coor_source = self.parameterAsSource({'INPUT': add_geometry_2, 'OUTPUT': ''}, self.INPUT, context)
            length_list = [[f['length']] for f in add_coor_source.getFeatures()]
            df2 = pd.DataFrame(length_list, columns=['length'])
            update_length(edge_df, df2)
            try:
                save_edges_npz(preproc_paths['edges_npz'], edge_df)
            except Exception:
                pass

        # --- 3) Split by lixel (cache-aware: depends on graph + lixel_length) ---
        qgis_split_output = preproc_paths['split_geojson']
        if not nc.has_split(cache_id, lixel_length):
            if os.path.exists(qgis_split_output):
                os.remove(qgis_split_output)
            processing.run("native:splitlinesbylength", {
                'INPUT': geo_path_2 + '|layername=edges',
                'LENGTH': lixel_length, 'OUTPUT': qgis_split_output})

        # --- 4) Project input points (cache-aware: depends on graph + point set) ---
        points_hash = NetworkCache.hash_points(coor_list)
        graph_output_path = self.folder_path + '/graph_output'
        graph_output_cache = nc.get_preproc_paths(
            cache_id, points_hash=points_hash
        )['graph_output']

        import shutil
        if nc.has_graph_output(cache_id, points_hash):
            shutil.copyfile(graph_output_cache, graph_output_path)
        else:
            data_arr = np.array(coor_list)
            distance_df = project_data_points_and_generate_points_layer(
                g, data_arr, self.folder_path, feedback
            )
            merge(edge_df, distance_df, nodes_num, self.folder_path)
            try:
                shutil.copyfile(graph_output_path, graph_output_cache)
            except Exception:
                pass

        feedback.pushInfo('End preparing road network, duration:{:.2f}s'.format(
            time.time() - prep_start))
        # End preparing road network

        # Start processing NKDV
        feedback.pushInfo('Start processing NKDV')
        feedback.pushInfo('Using kernel type: {} ({})'.format(kernel_type, self.KERNEL_OPTIONS[kernel_type]))
        start = time.time()
        example = NKDV(bandwidth=bandwidth, lixel_reg_length=lixel_length, kernel_type=kernel_type, method=6)
        example.set_data(self.folder_path + '/graph_output')
        example.compute()
        feedback.pushInfo('End NKDV computation, duration: {:.2f}s'.format(example.compute_time))
        end = time.time()
        duration = end - start
        if DEBUG_MODE:
            feedback.pushInfo('[DEBUG] End processing NKDV, duration:{}s'.format(duration))
        # End processing NKDV

        # Start present result
        feedback.pushInfo('Start present result')
        start = time.time()
        # feedback.pushInfo('Start read cpp result')
        result_io = StringIO(example.result)
        df_cplusplus = pd.read_csv(result_io, sep=' ', skiprows=1, names=['a', 'b', 'c', 'value'])['value']
        # end2 = time.time()
        # duration2 = end2 - start
        # feedback.pushInfo('End read cpp result, duration:{}s'.format(duration2))


        # feedback.pushInfo('Start open file')
        # start2 = time.time()
        with open(qgis_split_output) as file:
            df4 = gpd.read_file(file)
        # end2 = time.time()
        # duration2 = end2 - start2
        # feedback.pushInfo('End open file, duration:{}s'.format(duration2))
        # feedback.pushInfo('Start add_value')
        # start2 = time.time()
        df5 = add_kd_value(df4, df_cplusplus)
        # end2 = time.time()
        # duration2 = end2 - start2
        # feedback.pushInfo('End add_value, duration:{}s'.format(duration2))
        df5.drop(columns='fid', inplace=True)
        
        # Convert to EPSG:4326 (WGS84) for correct display in QGIS
        # The calculation was done in UTM (meters), but display needs lat/lon
        if df5.crs is not None and df5.crs.to_epsg() != 4326:
            if DEBUG_MODE:
                feedback.pushInfo(f'[DEBUG] Converting result from {df5.crs} to EPSG:4326 for display')
            df5 = df5.to_crs(epsg=4326)
        
        df5.to_file(path)
        # end2 = time.time()
        # duration2 = end2 - start2
        # feedback.pushInfo('End to file, duration:{}s'.format(duration2))
        # df5.to_file(self.folder_path + r'\output_shp.shp')
        # Set layer name, which will be displayed in ui.
        kernel_name = self.KERNEL_OPTIONS[kernel_type][:3].lower()  # e.g., 'epa' for Epanechnikov
        layer_name = 'nkdv_' + 'b' + str(int(bandwidth)) + '_k' + kernel_name + '_' + str(input_layer_name)
        # Set the path to the shapefile
        # You can also use Reds, Blues, Greys, Greens, Spectral to replace Turbo for display
        ramp_name = 'Turbo'
        value_field = 'value'
        num_classes = 20

        # You can also use the following classification method classes to replace QgsClassificationQuantile():
        # QgsClassificationEqualInterval() # equal interval
        # QgsClassificationQuantile() # equal count
        # QgsClassificationJenks() # natural breaks
        # QgsClassificationStandardDeviation()
        if DEBUG_MODE:
            feedback.pushInfo("[DEBUG] Start prepare layer")
        start2 = time.time()
        classification_method = QgsClassificationQuantile()
        # create layer
        v_layer = QgsVectorLayer(path, layer_name, "ogr")
        # add layer to the project

        # layer = QgsProject().instance().mapLayersByName(layer_name)[0]

        # format = QgsRendererRangeLabelFormat()
        # format.setFormat("%1 - %2")
        # format.setPrecision(2)
        # format.setTrimTrailingZeroes(True)

        classification_method.setLabelFormat("%1 - %2")
        classification_method.setLabelFormat("%1 - %2")
        classification_method.setLabelPrecision(2)
        classification_method.setLabelTrimTrailingZeroes(True)
        end2 = time.time()
        duration2 = end2 - start2
        if DEBUG_MODE:
            feedback.pushInfo("[DEBUG] End prepare latyer, duration:{}s".format(duration2))

        if DEBUG_MODE:
            feedback.pushInfo("[DEBUG] Start render layer")
        start2 = time.time()
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

        # ---- Fade out the lowest-density classes so background roads in the
        # outer/peripheral areas become transparent and don't clutter the map.
        # FULLY_HIDDEN_FRACTION : fraction of the lowest classes rendered fully transparent.
        # FADE_FRACTION         : the next fraction is rendered with a linear alpha ramp
        #                         from 0 -> 1, giving a smooth visual transition.
        FULLY_HIDDEN_FRACTION = 0.15
        FADE_FRACTION = 0.10
        n_classes_actual = renderer.ranges().__len__()
        n_hidden = max(1, int(round(n_classes_actual * FULLY_HIDDEN_FRACTION)))
        n_fade   = max(1, int(round(n_classes_actual * FADE_FRACTION)))
        for idx, rng in enumerate(renderer.ranges()):
            sym = rng.symbol().clone()
            if idx < n_hidden:
                sym.setOpacity(0.0)
            elif idx < n_hidden + n_fade:
                sym.setOpacity((idx - n_hidden + 1) / float(n_fade + 1))
            else:
                sym.setOpacity(1.0)
            renderer.updateRangeSymbol(idx, sym)

        v_layer.setRenderer(renderer)
        v_layer.triggerRepaint()
        end2 = time.time()
        duration2 = end2 - start2
        if DEBUG_MODE:
            feedback.pushInfo("[DEBUG] End render layer, duration:{}s".format(duration2))

        QgsProject.instance().addMapLayer(v_layer)


        end = time.time()
        duration = end - start
        feedback.pushInfo('End present result, duration:{}s'.format(duration))
        # End present result
        return v_layer

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'networkkdv(NKDV)'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr("Network KDV (NKDV)")

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return NKDVAlgorithm()

    def helpUrl(self):
        return "https://github.com/edisonchan2013928/PyNKDV"

    def shortDescription(self):
        return "Efficient and accurate network kernel density visualization."

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icons/nkdv.png'))