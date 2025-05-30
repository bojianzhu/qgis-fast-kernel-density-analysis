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
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterEnum,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterField,
    QgsMessageLog,
    Qgis,
    QgsProject,
    QgsRasterLayer,
    QgsStyle
)
from qgis.PyQt.QtGui import QIcon
from .libkdv import kdv
from .rasterstyle import applyPseudocolor
import pandas as pd
from osgeo import gdal
from datetime import datetime
import time

MESSAGE_CATEGORY = 'Fast Density Analysis'


class KDVAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    LONGITUDEFIELD = 'LONGITUDEFIELD'
    LATITUDEFIELD = 'LATITUDEFIELD'
    WIDTH = 'WIDTH'
    HEIGHT = 'HEIGHT'
    SPATIALBANDWIDTH = 'SPATIALBANDWIDTH'
    RAMPNAME = 'RAMPNAME'
    INVERT = 'INVERT'
    INTERPOLATION = 'INTERPOLATION'
    MODE = 'MODE'
    CLASSES = 'CLASSES'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                self.tr('Input point layer'),
                [QgsProcessing.TypeVectorPoint]
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.LONGITUDEFIELD,
                self.tr('Longitude'),
                None,
                self.INPUT
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.LATITUDEFIELD,
                self.tr('Latitude'),
                None,
                self.INPUT
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.WIDTH,
                'Width',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=800, optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.HEIGHT,
                'Height',
                type=QgsProcessingParameterNumber.Integer,
                minValue=0,
                defaultValue=640,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SPATIALBANDWIDTH,
                'Spatial bandwidth (meters)',
                type=QgsProcessingParameterNumber.Double,
                minValue=0,
                defaultValue=1000,
                optional=False
            )
        )
        if Qgis.QGIS_VERSION_INT >= 32200:
            param = QgsProcessingParameterString(
                self.RAMPNAME,
                'Select color ramp',
                defaultValue='Reds',
                optional=False
            )
            param.setMetadata(
                {
                    'widget_wrapper': {
                        'value_hints': QgsStyle.defaultStyle().colorRampNames()
                    }
                }
            )
        else:
            param = QgsProcessingParameterEnum(
                self.RAMPNAME,
                'Select color ramp',
                options=QgsStyle.defaultStyle().colorRampNames(),
                defaultValue=0,
                optional=False
            )
        self.addParameter(param)
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INVERT,
                'Invert color ramp',
                False,
                optional=False)
        )
        # Chose Kernel shape
        # param = QgsProcessingParameterEnum('KERNEL', 'Kernel shape',
        #                                    options=['Quartic', 'Triangular', 'Uniform', 'Triweight', 'Epanechnikov'],
        #                                    defaultValue=0, optional=False)
        # param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        # self.addParameter(param)
        # param = QgsProcessingParameterNumber('DECAY', 'Decay ratio (Triangular kernels only)',
        #                                      type=QgsProcessingParameterNumber.Double, defaultValue=0, minValue=-100,
        #                                      maxValue=100, optional=False)
        # param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        # self.addParameter(param)

        param = QgsProcessingParameterEnum(
            self.INTERPOLATION,
            'Interpolation',
            options=['Discrete', 'Linear', 'Exact'],
            defaultValue=0,
            optional=False)
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        param = QgsProcessingParameterEnum(
            self.MODE,
            'Mode',
            options=['Continuous', 'Equal Interval', 'Quantile'],
            defaultValue=1,
            optional=False)
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        param = QgsProcessingParameterNumber(
            self.CLASSES,
            'Number of gradient colors',
            QgsProcessingParameterNumber.Integer,
            defaultValue=15,
            minValue=2,
            optional=False)
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)

        # Output
        # self.addParameter(
        #     QgsProcessingParameterRasterDestination(self.OUTPUT, 'Output KDV heatmap',
        #                                             createByDefault=True, defaultValue=None)
        # )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        lyr = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        fldLon = self.parameterAsString(parameters, self.LONGITUDEFIELD, context)
        fldLat = self.parameterAsString(parameters, self.LATITUDEFIELD, context)
        row_pixels = self.parameterAsInt(parameters, self.WIDTH, context)
        col_pixels = self.parameterAsInt(parameters, self.HEIGHT, context)
        bandwidth_s = self.parameterAsDouble(parameters, self.SPATIALBANDWIDTH, context)

        if Qgis.QGIS_VERSION_INT >= 32200:
            ramp_name = self.parameterAsString(parameters, self.RAMPNAME, context)
        else:
            ramp_name = self.parameterAsEnum(parameters, self.RAMPNAME, context)
        invert = self.parameterAsBool(parameters, self.INVERT, context)
        interp = self.parameterAsInt(parameters, self.INTERPOLATION, context)
        mode = self.parameterAsInt(parameters, self.MODE, context)
        num_classes = self.parameterAsInt(parameters, self.CLASSES, context)
        rlayer = processKDV(lyr, fldLon, fldLat, row_pixels, col_pixels, bandwidth_s, ramp_name, invert, interp, mode,
                            num_classes, feedback)

        return {self.OUTPUT: rlayer}

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'kerneldensityvisualization(KDV)'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr("Kernel density visualization (KDV)")

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return KDVAlgorithm()

    def helpUrl(self):
        return "https://github.com/libkdv/libkdv"

    def shortDescription(self):
        return "Efficient and accurate kernel density visualization."

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icons/kdv.png'))


def processKDV(lyr, fldLon, fldLat, row_pixels, col_pixels, bandwidth_s, ramp_name, invert, interp, mode, num_classes,
               feedback):
    # Get currentTime
    currentTime =datetime.now()
    # toString
    timeStr = currentTime.strftime('%Y-%m-%d %H-%M-%S')
    # Current project path
    prjPath = QgsProject.instance().homePath()
    savePath = prjPath + "/temp/KDV/" + timeStr
    # Create save directory
    try:
        os.makedirs(savePath)
    except FileExistsError:
        pass
    except Exception as e:
        feedback.pushInfo('Create diectory failed, error:{}'.format(e))
        # QgsMessageLog.logMessage("Create diectory failed, error:{}".format(e), MESSAGE_CATEGORY, level=Qgis.Info)

    # Start aggregate features
    feedback.pushInfo('Start aggregate features')
    start = time.time()
    data = pd.DataFrame([feat.attributes() for feat in lyr.getFeatures()], columns=[field.name() for field in lyr.fields()])
    data = data.loc[:, [fldLat, fldLon]]
    data.rename(columns={fldLat: 'lat', fldLon: 'lon'}, inplace=True)
    end = time.time()
    duration = end - start
    feedback.setProgress(40)
    feedback.pushInfo('End aggregate features, duration:{}s'.format(duration))
    if feedback.isCanceled():
        return {}
    # End aggregate features

    # Start KDV
    feedback.pushInfo('Start KDV')
    start = time.time()
    kdv_data = kdv(data, GPS=True, KDV_type='KDV', bandwidth=bandwidth_s, row_pixels=row_pixels, col_pixels=col_pixels)
    kdv_data.compute()
    end = time.time()
    duration = end - start
    feedback.setProgress(70)
    feedback.pushInfo('End KDV, duration:{}s'.format(duration))
    if feedback.isCanceled():
        return {}
    # End KDV

    # Start generate KDV raster layer
    feedback.pushInfo('Start generate KDV raster layer')
    start = time.time()
    kdv_data.result.rename(columns={"lon": "x", "lat": "y", "val": "value"}, inplace=True)
    # Sorted according to first y minus then x increasing (from top left corner, top to bottom left to right)
    result = kdv_data.result.sort_values(by=["y", "x"], ascending=[False, True])
    path = savePath + "/Heatmap"
    result.to_csv(path + ".xyz", index=False, header=False, sep=" ")
    opts = gdal.TranslateOptions(
            outputSRS="EPSG:4326"
        )
    temp = gdal.Translate(path + ".tif", path + ".xyz", options=opts)
    temp = None
    os.remove(path + '.xyz')
    fn = path + '.tif'
    rlayer = QgsRasterLayer(fn, 'Heatmap')
    end = time.time()
    duration = end - start
    feedback.setProgress(100)
    feedback.pushInfo('End generate KDV raster layer, duration:{}s'.format(duration))
    if feedback.isCanceled():
        return {}
    applyPseudocolor(rlayer, ramp_name, invert, interp, mode, num_classes)
    QgsProject.instance().addMapLayer(rlayer)
    return rlayer
