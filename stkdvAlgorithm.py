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
    QgsProcessingParameterDateTime,
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


def _to_unix_seconds(series, feedback=None):
    """
    Auto-detect the time column format and convert to Unix timestamp (seconds).

    Supports:
    - Numeric Unix timestamps in seconds (e.g. 1688342400)
    - Numeric Unix timestamps in milliseconds (e.g. 1688342400000)
    - Python datetime / pandas Timestamp objects
    - QDateTime objects (from QGIS attribute table)
    - QDate objects
    - Date / datetime strings parseable by pandas (e.g. '2023-07-03 12:30:00')
    """
    # Try QDateTime / QDate first via duck-typing (avoid importing here)
    def _convert_one(v):
        if v is None:
            return None
        # QDateTime has toPyDateTime(); QDate has toPyDate()
        to_pydt = getattr(v, 'toPyDateTime', None)
        if callable(to_pydt):
            try:
                return to_pydt().timestamp()
            except Exception:
                pass
        to_pyd = getattr(v, 'toPyDate', None)
        if callable(to_pyd):
            try:
                return datetime.combine(to_pyd(), datetime.min.time()).timestamp()
            except Exception:
                pass
        # QDateTime fallback: toSecsSinceEpoch
        to_secs = getattr(v, 'toSecsSinceEpoch', None)
        if callable(to_secs):
            try:
                return float(to_secs())
            except Exception:
                pass
        return v

    converted = series.map(_convert_one)

    # Fast path: already numeric
    numeric = pd.to_numeric(converted, errors='coerce')
    if numeric.notna().sum() == converted.notna().sum() and converted.notna().any():
        max_val = numeric.dropna().abs().max()
        # Heuristic: > 1e12 likely milliseconds (year 33658+ if seconds)
        if max_val is not None and max_val > 1e12:
            if feedback is not None:
                feedback.pushInfo('Time field detected as milliseconds; converting to seconds.')
            numeric = numeric / 1000.0
        else:
            if feedback is not None:
                feedback.pushInfo('Time field detected as numeric Unix timestamp (seconds).')
        return numeric.astype('float64')

    # Otherwise parse as datetime strings / objects
    if feedback is not None:
        feedback.pushInfo('Time field detected as datetime; converting to Unix timestamp (seconds).')
    parsed = pd.to_datetime(converted, errors='coerce', utc=False)
    # Convert datetime64[ns] to seconds since epoch as float
    return parsed.view('int64').astype('float64') / 1e9


class STKDVAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    LONGITUDEFIELD = 'LONGITUDEFIELD'
    LATITUDEFIELD = 'LATITUDEFIELD'
    TIMEFIELD = 'TIMEFIELD'
    WIDTH = 'WIDTH'
    HEIGHT = 'HEIGHT'
    TIMEAXIS = 'TIMEAXIS'
    SPATIALBANDWIDTH = 'SPATIALBANDWIDTH'
    TEMPORALBANDWIDTH = 'TEMPORALBANDWIDTH'
    STARTTIME = 'STARTTIME'
    ENDTIME = 'ENDTIME'
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
            QgsProcessingParameterField(
                self.TIMEFIELD,
                self.tr('Time'),
                None,
                self.INPUT
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.WIDTH,
                'Width',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=400,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.HEIGHT,
                'Height',
                type=QgsProcessingParameterNumber.Integer, minValue=0,
                defaultValue=320,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TIMEAXIS,
                'Time-axis',
                type=QgsProcessingParameterNumber.Integer, minValue=0,
                defaultValue=8,
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
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TEMPORALBANDWIDTH,
                'Temporal bandwidth (days)',
                type=QgsProcessingParameterNumber.Double,
                minValue=0,
                defaultValue=6,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterDateTime(
                self.STARTTIME,
                'Start'
            )
        )
        self.addParameter(
            QgsProcessingParameterDateTime(
                self.ENDTIME,
                'End'
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
        fldTime = self.parameterAsString(parameters, self.TIMEFIELD, context)
        row_pixels = self.parameterAsInt(parameters, self.WIDTH, context)
        col_pixels = self.parameterAsInt(parameters, self.HEIGHT, context)
        t_pixels = self.parameterAsInt(parameters, self.TIMEAXIS, context)
        bandwidth_s = self.parameterAsDouble(parameters, self.SPATIALBANDWIDTH, context)
        bandwidth_t = self.parameterAsDouble(parameters, self.TEMPORALBANDWIDTH, context)
        startTime = self.parameterAsDateTime(parameters, self.STARTTIME, context)
        endTime = self.parameterAsDateTime(parameters, self.ENDTIME, context)

        startTime = startTime.toString("yyyy-MM-dd hh:mm:ss")
        endTime = endTime.toString("yyyy-MM-dd hh:mm:ss")

        if Qgis.QGIS_VERSION_INT >= 32200:
            ramp_name = self.parameterAsString(parameters, self.RAMPNAME, context)
        else:
            ramp_name = self.parameterAsEnum(parameters, self.RAMPNAME, context)
        invert = self.parameterAsBool(parameters, self.INVERT, context)
        interp = self.parameterAsInt(parameters, self.INTERPOLATION, context)
        mode = self.parameterAsInt(parameters, self.MODE, context)
        num_classes = self.parameterAsInt(parameters, self.CLASSES, context)
        rlayers = processSTKDV(lyr, fldLat, fldLon, fldTime, row_pixels, col_pixels, t_pixels, bandwidth_s, bandwidth_t,
                               startTime, endTime, ramp_name, invert, interp, mode, num_classes, feedback)

        return {self.OUTPUT: rlayers}

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'spatiotemporalkdv(STKDV)'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr("Spatiotemporal KDV (STKDV)")

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return STKDVAlgorithm()

    def helpUrl(self):
        return "https://github.com/libkdv/libkdv"

    def shortDescription(self):
        return "Efficient and accurate spatiotemporal kernel density visualization."

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icons/stkdv.png'))


def processSTKDV(lyr, fldLat, fldLon, fldTime, row_pixels, col_pixels, t_pixels, bandwidth_s, bandwidth_t,
                 startTime, endTime, ramp_name, invert, interp, mode, num_classes, feedback):
    currentTime = datetime.now()
    timeStr = currentTime.strftime('%Y-%m-%d %H-%M-%S')
    prjPath = QgsProject.instance().homePath()
    savePath = prjPath + "/temp/STKDV/" + timeStr
    try:
        os.makedirs(savePath)
    except FileExistsError:
        pass
    except Exception as e:
        feedback.pushInfo('Create diectory failed, error:{}'.format(e))
        # QgsMessageLog.logMessage("Create diectory failed, error:{}".format(e), MESSAGE_CATEGORY,
        #                              level=Qgis.Info)

    # Start aggregate features
    feedback.pushInfo('Start aggregate features')
    start = time.time()
    data = pd.DataFrame([feat.attributes() for feat in lyr.getFeatures()],
                        columns=[field.name() for field in lyr.fields()])
    data = data.loc[:, [fldLat, fldLon, fldTime]]
    data.rename(columns={fldLat: 'lat', fldLon: 'lon', fldTime: 't'}, inplace=True)

    # Auto-detect and convert time column to Unix timestamp (seconds)
    data['t'] = _to_unix_seconds(data['t'], feedback)
    data = data.dropna(subset=['t'])
    if data.empty:
        feedback.pushInfo('No valid time values after parsing.')
        return {'Empty.'}

    dt = datetime.strptime(startTime, '%Y-%m-%d %H:%M:%S')
    st = dt.timestamp()
    dt = datetime.strptime(endTime, '%Y-%m-%d %H:%M:%S')
    et = dt.timestamp()
    # Select the data in the time period
    condition = (data['t'] >= st) & (data['t'] <= et)
    filtered_data = data[condition]
    if filtered_data.empty:
        return {'Empty.'}
    end = time.time()
    duration = end - start
    feedback.setProgress(40)
    feedback.pushInfo('End aggregate features, duration:{}s'.format(duration))

    if feedback.isCanceled():
        return {}
    # End aggregate features

    # Start STKDV
    feedback.pushInfo('Start STKDV')
    start = time.time()
    kdv_data = kdv(filtered_data, GPS=True, KDV_type='STKDV', bandwidth=bandwidth_s, bandwidth_t=bandwidth_t,
                   row_pixels=row_pixels, col_pixels=col_pixels, t_pixels=t_pixels)
    kdv_data.compute()
    end = time.time()
    duration = end - start
    feedback.setProgress(70)
    feedback.pushInfo('End STKDV, duration:{:.3f}s'.format(duration))
    if feedback.isCanceled():
        return {}
    # End STKDV

    # Start generate STKDV raster layer
    feedback.pushInfo('Start generate STKDV raster layer')
    start = time.time()
    import numpy as np
    from osgeo import osr

    kdv_data.result.rename(columns={"lon": "x", "lat": "y", "val": "value"}, inplace=True)

    # Global colour range, shared across all time slices.
    min_val = float(kdv_data.result['value'].min())
    max_val = float(kdv_data.result['value'].max())
    if max_val <= min_val:
        max_val = min_val + 1e-12

    # Build canonical axes from ALL data (not just first frame). This is
    # robust to whatever internal order the C layer uses.
    xs_unique = np.sort(kdv_data.result['x'].unique())
    ys_unique = np.sort(kdv_data.result['y'].unique())[::-1]  # north -> south
    n_cols = len(xs_unique)
    n_rows = len(ys_unique)

    # Geotransform shared by every frame
    x_step = (xs_unique[-1] - xs_unique[0]) / (n_cols - 1) if n_cols > 1 else 1.0
    y_step = (ys_unique[0] - ys_unique[-1]) / (n_rows - 1) if n_rows > 1 else 1.0
    geotransform = (
        xs_unique[0] - x_step / 2.0,
        x_step,
        0.0,
        ys_unique[0] + y_step / 2.0,
        0.0,
        -y_step,
    )

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs_wkt = srs.ExportToWkt()

    NODATA = float('nan')
    driver = gdal.GetDriverByName('GTiff')
    ys_asc = ys_unique[::-1]  # ascending copy for searchsorted

    # ---- Per-frame: groupby + searchsorted into a (n_rows, n_cols) Float32 raster ----
    grouped = kdv_data.result.groupby('t', sort=True)

    rlayers = []
    i = 0
    for ts_sec, group in grouped:
        if feedback.isCanceled():
            return {}

        x_arr = group['x'].to_numpy()
        y_arr = group['y'].to_numpy()
        v_arr = group['value'].to_numpy(dtype=np.float32)

        xi = np.searchsorted(xs_unique, x_arr)
        # ys_unique is descending; map each y to its row index by searching
        # the ascending copy then flipping.
        yi = (n_rows - 1) - np.searchsorted(ys_asc, y_arr)

        # Defensive clamp (should never fire since axes were built from
        # the same data, but just in case of float-equality edge cases).
        np.clip(xi, 0, n_cols - 1, out=xi)
        np.clip(yi, 0, n_rows - 1, out=yi)

        arr = np.full((n_rows, n_cols), NODATA, dtype=np.float32)
        arr[yi, xi] = v_arr
        arr[arr == 0.0] = NODATA  # zeros -> transparent

        dt = datetime.fromtimestamp(float(ts_sec))
        path = savePath + "/STHeatmap " + dt.strftime("%Y-%m-%d %H-%M-%S")
        fn = path + ".tif"

        ds = driver.Create(fn, n_cols, n_rows, 1, gdal.GDT_Float32,
                           options=['COMPRESS=LZW', 'TILED=YES'])
        ds.SetGeoTransform(geotransform)
        ds.SetProjection(srs_wkt)
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(NODATA)
        band.WriteArray(arr)
        band.FlushCache()
        ds = None

        rlayer = QgsRasterLayer(fn, "STHeatmap" + dt.strftime("%Y-%m-%d %H-%M-%S"))
        applyPseudocolor(rlayer, ramp_name, invert, interp, mode, num_classes,
                         vmin=min_val if min_val > 0 else 1e-12,
                         vmax=max_val)
        QgsProject.instance().addMapLayer(rlayer)
        i += 1
        feedback.setProgress(i / t_pixels * 30 + 70)
        rlayers.append(rlayer)

    end = time.time()
    duration = end - start
    feedback.pushInfo('End generate STKDV raster layer, duration:{}s'.format(duration))
    # End generate STKDV raster layer
    return rlayers