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
    QgsProcessingParameterNumber
    )
import time

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
    FOLDER_PATH = 'FOLDER_PATH'

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
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                self.tr('Output File'),
                fileFilter='GeoPackage (*.gpkg *.GPKG);;ESRI Shapefile (*.shp *.SHP)'
            )
        )
        # self.addParameter(QgsProcessingParameterFileDestination(
        #     name=self.OUTPUT, description=self.tr('Output file'))
        # )

    def processAlgorithm(self, parameters, context, feedback):
        self.folder_path = self.parameterAsFileOutput(parameters, self.FOLDER_PATH, context)
        print(self.folder_path)
        bandwidth = self.parameterAsDouble(parameters, self.BANDWIDTH, context)
        lixel_length = self.parameterAsDouble(parameters, self.LIXEL_LENGTH, context)
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
                                     lixel_length=lixel_length, path=output_path, input_layer_name=input_layer_name, feedback = feedback)

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

    def run_nkdv(self, path, coor_list, context, input_layer_name, feedback, bandwidth=1000, lixel_length=5):
        data_df = pd.DataFrame(coor_list, columns=['lon', 'lat'])
        lat_max = data_df['lat'].max()  # north
        lat_min = data_df['lat'].min()  # south
        lon_max = data_df['lon'].max()  # east
        lon_min = data_df['lon'].min()  # west

        # Start downloading map
        feedback.pushInfo('Start downloading map')
        start = time.time()
        # g1 = ox.graph_from_bbox(lat_max, lat_min, lon_max, lon_min, simplify=True, network_type='drive')
        ox.settings.use_cache = False

        query = """ 
        (
        node["highway"](""" + str(lat_min) + ',' + str(lon_min) + ',' + str(lat_max) + ',' + str(lon_max) + """);
        way["highway"](""" + str(lat_min) + ',' + str(lon_min) + ',' + str(lat_max) + ',' + str(lon_max) + """);
        relation["highway"](""" + str(lat_min) + ',' + str(lon_min) + ',' + str(lat_max) + ',' + str(lon_max) + """);
        );
        (._;>;);
        out body;
            """
        api = API()
        result = api.get(query, verbosity='body', responseformat='xml')
        with open(os.path.join(self.folder_path + "testio.xml"), mode="w", encoding='utf-8') as f:
            f.write(result)

        g1 = ox.graph_from_xml(os.path.join(self.folder_path + "testio.xml"), simplify=False)

        # ox.config(use_cache=True, cache_folder=self.folder_path)
        # g1 = ox.graph_from_bbox(lat_max, lat_min, lon_max, lon_min, simplify=True, network_type='drive')
        # g1 = ox.graph_from_point((lat_avg, lon_avg), dist=max(abs(lat_max-lat_min), abs(lon_max-lon_min)), dist_type='bbox', network_type='drive', simplify=True)
        # g1 = ox.graph_from_place('Detroit, Wayne County, Michigan, USA', network_type='drive')
        # print(g1.number_of_edges())
        # print(g1.number_of_nodes())
        # print('finish downloading g1')

        gc1 = ox.consolidate_intersections(ox.project_graph(g1), tolerance=0.5, rebuild_graph=True)
        undi_gc1 = gc1.to_undirected()
        single_undi_gc1 = nx.Graph(undi_gc1)
        g = nx.MultiGraph(single_undi_gc1)
        nodes_num = g.number_of_nodes()
        fix_direction(g)
        end = time.time()
        duration = end - start
        feedback.pushInfo('End downloading map, duration:{}s'.format(duration))
        # End downloading map

        # Start processing edges
        feedback.pushInfo('Start processing edges')
        start = time.time()
        edge_df = process_edges(g)
        geo_path_1 = self.folder_path + '/geo1.gpkg'
        ox.save_graph_geopackage(g, geo_path_1)
        df1 = gpd.read_file(geo_path_1, layer='edges')
        geo_path_2 = self.folder_path + '/simplified.gpkg'
        df1 = df1[['geometry']]
        df1.to_file(geo_path_2, driver='GPKG', layer='edges')

        add_geometry_2 = processing.run("qgis:exportaddgeometrycolumns",
                                        {'INPUT': geo_path_2 + '|layername=edges', 'CALC_METHOD': 0,
                                         'OUTPUT': "TEMPORARY_OUTPUT"})['OUTPUT']

        add_coor_source = self.parameterAsSource({'INPUT': add_geometry_2, 'OUTPUT': ''}, self.INPUT, context)
        length_list = []
        for current, f in enumerate(add_coor_source.getFeatures()):
            length_list.append([f['length']])

        # print(length_list[0])
        df2 = pd.DataFrame(length_list, columns=['length'])
        # print(type(df2))
        update_length(edge_df, df2)
        end = time.time()
        duration = end - start
        feedback.pushInfo('End processing edges, duration:{}s'.format(duration))
        # End processing edges

        # Start projecting points to the road
        feedback.pushInfo('Start projecting points to the road')
        start = time.time()
        data_arr = np.array(coor_list)
        distance_df = project_data_points_and_generate_points_layer(g, data_arr, self.folder_path, feedback)
        merge(edge_df, distance_df, nodes_num, self.folder_path)

        end = time.time()
        duration = end - start
        feedback.pushInfo('End projecting points to the road, duration:{}s'.format(duration))
        # End projecting points to the road

        # Start splitting roads
        feedback.pushInfo('Start splitting roads')
        start = time.time()
        # split_road = processing.run("native:splitlinesbylength", {
        #     'INPUT': geo_path_2 + '|layername=edges',
        #     'LENGTH': lixel_size, 'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
        qgis_split_output = self.folder_path + '/split_by_qgis.geojson'
        processing.run("native:splitlinesbylength", {
            'INPUT': geo_path_2 + '|layername=edges',
            'LENGTH': lixel_length, 'OUTPUT': qgis_split_output})

        end = time.time()
        duration = end - start
        feedback.pushInfo('End splitting roads, duration:{}s'.format(duration))
        # End splitting roads

        # Start processing NKDV
        feedback.pushInfo('Start processing NKDV')
        start = time.time()
        example = NKDV(bandwidth=bandwidth, lixel_reg_length=lixel_length, method=3)
        example.set_data(self.folder_path + '/graph_output')
        example.compute()
        end = time.time()
        duration = end - start
        feedback.pushInfo('End processing NKDV, duration:{}s'.format(duration))
        # End processing NKDV

        # Start present result
        feedback.pushInfo('Start present result')
        start = time.time()
        feedback.pushInfo('Start read cpp result')
        result_io = StringIO(example.result)
        df_cplusplus = pd.read_csv(result_io, sep=' ', skiprows=1, names=['a', 'b', 'c', 'value'])['value']
        end2 = time.time()
        duration2 = end2 - start
        feedback.pushInfo('End read cpp result, duration:{}s'.format(duration2))

        start2 = time.time()
        feedback.pushInfo('Start open file')
        with open(qgis_split_output) as file:
            df4 = gpd.read_file(file)
        end2 = time.time()
        duration2 = end2 - start2
        feedback.pushInfo('End open file, duration:{}s'.format(duration2))
        feedback.pushInfo('Start add_value')
        start2 = time.time()
        df5 = add_kd_value(df4, df_cplusplus)
        end2 = time.time()
        duration2 = end2 - start2
        feedback.pushInfo('End add_value, duration:{}s'.format(duration2))
        df5.drop(columns='fid', inplace=True)
        feedback.pushInfo('Start to file')
        start2 = time.time()
        df5.to_file(path)
        end2 = time.time()
        duration2 = end2 - start2
        feedback.pushInfo('End to file, duration:{}s'.format(duration2))
        # df5.to_file(self.folder_path + r'\output_shp.shp')
        # Set layer name, which will be displayed in ui.
        layer_name = 'nkdv_' + 'b' + str(int(bandwidth)) + '_' + str(input_layer_name)
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
        feedback.pushInfo("Start prepare layer")
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
        feedback.pushInfo("End prepare latyer, duration:{}s".format(duration2))

        feedback.pushInfo("Start render layer")
        start2 = time.time()
        default_style = QgsStyle().defaultStyle()
        color_ramp = default_style.colorRamp(ramp_name)

        renderer = QgsGraduatedSymbolRenderer()
        renderer.setClassAttribute(value_field)
        renderer.setClassificationMethod(classification_method)
        # renderer.setLabelFormat(format)
        renderer.updateClasses(v_layer, num_classes)
        renderer.updateColorRamp(color_ramp)
        v_layer.setRenderer(renderer)
        end2 = time.time()
        duration2 = end2 - start2
        feedback.pushInfo("End render layer, duration:{}s".format(duration2))

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