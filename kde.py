from .libkdv import kdv
from .rasterstyle import applyPseudocolor
import pandas as pd
from osgeo import gdal
from qgis.core import QgsMessageLog, Qgis, QgsProject
import os
import datetime
import time

def processKDV(self, lyr, fldLat, fldLon, row_pixels, col_pixels, bandwidth_s):
    # Get currentTime
    currentTime = datetime.datetime.now()
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
        QgsMessageLog.logMessage("Create diectory failed, error:{}".format(e), "Fast Kernel Density Analysis", level=Qgis.Info)

    # Start append
    QgsMessageLog.logMessage("Start append", "Fast Kernel Density Analysis", level=Qgis.Info)
    start = time.time()
    data = pd.DataFrame(columns=['lat', 'lon'])
    # Append features
    for feature in lyr.getFeatures():
        data = pd.concat([data, pd.DataFrame({'lat':[feature.attribute(fldLat)], 'lon':[feature.attribute(fldLon)]})])
    end = time.time()
    duration = end - start
    QgsMessageLog.logMessage("End append, duration:{}s".format(duration), "Fast Kernel Density Analysis", level=Qgis.Info)
    # End append

    # Start KDV
    QgsMessageLog.logMessage("Start KDV", "Fast Kernel Density Analysis", level=Qgis.Info)
    start = time.time()
    kdv_data = kdv(data, GPS=True, KDV_type='KDV', bandwidth=bandwidth_s, row_pixels=row_pixels, col_pixels=col_pixels)
    kdv_data.compute()
    end = time.time()
    duration = end - start
    QgsMessageLog.logMessage("End KDV, duration:{}s".format(duration), "Fast Kernel Density Analysis", level=Qgis.Info)
    # End KDV

    # Start generate KDV raster layer
    QgsMessageLog.logMessage("Start generate KDV raster layer", "Fast Kernel Density Analysis", level=Qgis.Info)
    start = time.time()
    kdv_data.result.rename(columns={"lon": "x", "lat": "y", "val": "value"}, inplace=True)
    # Sorted according to first y minus then x increasing (from top left corner, top to bottom left to right)
    result = kdv_data.result.sort_values(by=["y", "x"], ascending=[False, True])
    path = savePath + "/Heatmap"
    result.to_csv(path + ".xyz", index=False, header=False, sep=" ")
    demn = gdal.Translate(path + ".tif", path + ".xyz", outputSRS="EPSG:4326")
    demn = None
    os.remove(path + '.xyz')
    fn = path + '.tif'
    rlayer = self.iface.addRasterLayer(fn)
    end = time.time()
    duration = end - start
    QgsMessageLog.logMessage("End generate KDV raster layer, duration:{}s".format(duration), "Fast Kernel Density Analysis", level= Qgis.Info)
    # End generate KDV raster layer

    applyPseudocolor(rlayer)

def processSTKDV(self, lyr, fldLat, fldLon, fldTime, row_pixels, col_pixels, t_pixels, bandwidth_s, bandwidth_t, startTime, endTime):
    currentTime = datetime.datetime.now()
    timeStr = currentTime.strftime('%Y-%m-%d %H-%M-%S')
    prjPath = QgsProject.instance().homePath()
    savePath = prjPath+"/temp/STKDV/"+timeStr
    try:
        os.makedirs(savePath)
    except FileExistsError:
        pass
    except Exception as e:
        QgsMessageLog.logMessage("Create diectory failed, error:{}".format(e), "Fast Kernel Density Analysis", level=Qgis.Info)

    # Start append
    QgsMessageLog.logMessage("Start append", "Fast Kernel Density Analysis", level=Qgis.Info)
    start = time.time()
    data = pd.DataFrame(columns=['lat','lon', 't'])
    # Append features
    for feature in lyr.getFeatures():
        data = pd.concat([data, pd.DataFrame({'lat':[feature.attribute(fldLat)], 'lon':[feature.attribute(fldLon)], 't':[feature.attribute(fldTime)]})])
    end = time.time()
    duration = end - start
    QgsMessageLog.logMessage("End append, duration:{}s".format(duration), "Fast Kernel Density Analysis", level=Qgis.Info)
    # End append

    # Start STKDV
    QgsMessageLog.logMessage("Start STKDV", "Fast Kernel Density Analysis", level=Qgis.Info)
    start = time.time()
    kdv_data = kdv(data, GPS=True, KDV_type='STKDV', bandwidth=bandwidth_s, bandwidth_t=bandwidth_t, row_pixels=row_pixels, col_pixels=col_pixels, t_pixels=t_pixels)
    kdv_data.compute()
    end = time.time()
    duration = end - start
    QgsMessageLog.logMessage("End STKDV, duration:{}s".format(duration), "Fast Kernel Density Analysis", level=Qgis.Info)
    # End STKDV

    # Start generate STKDV raster layer
    QgsMessageLog.logMessage("Start generate STKDV raster layer", "Fast Kernel Density Analysis", level=Qgis.Info)
    start = time.time()
    kdv_data.result.rename(columns={"lon": "x", "lat": "y", "val": "value"}, inplace=True)

    # Convert time column to timestamp type
    kdv_data.result['t'] = pd.to_datetime(kdv_data.result['t'], unit='s')
    # Select the data in the time period
    condition = (kdv_data.result['t'] >= startTime) & (kdv_data.result['t'] <= endTime)
    filtered_result = kdv_data.result[condition]
    # QgsMessageLog.logMessage("filtered_result:{}".format(filtered_result), "Fast Kernel Density Analysis", level=Qgis.Info)

    # Group by time
    grouped = filtered_result.groupby('t').apply(lambda x: x.reset_index(drop=True))

    # Iterate through each group and generate a STKDV Heatmap for each group
    for name, group in grouped.groupby(level=0):
        # Delete Time Column
        group = group.drop('t', axis=1)
        # QgsMessageLog.logMessage("name:{}\ngroup:{}".format(name, group), "Fast Kernel Density Analysis", level=Qgis.Info)
        # Sorted according to first y minus then x increasing (from top left corner, top to bottom left to right)
        result = group.sort_values(by=["y", "x"], ascending=[False, True])
        path = savePath + "/STHeatmap " + name.strftime("%Y-%m-%d %H-%M-%S")
        result.to_csv(path + ".xyz", index=False, header=False, sep=" ")
        temp = gdal.Translate(path + ".tif", path + ".xyz", outputSRS="EPSG:4326")
        temp = None
        os.remove(path + ".xyz")
        fn = path + ".tif"
        rlayer = self.iface.addRasterLayer(fn)

        applyPseudocolor(rlayer)

    end = time.time()
    duration = end - start
    QgsMessageLog.logMessage("End generate STKDV raster layer, duration:{}s".format(duration), "Fast Kernel Density Analysis", level=Qgis.Info)
    # End generate STKDV raster layer
