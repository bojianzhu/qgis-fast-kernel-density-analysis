# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Fast Density Analysis
                                 A QGIS plugin
 A fast kernel density visualization plugin for geospatial analytics
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""
__author__ = 'LibKDV Group'
__date__ = '2023-07-03'
__copyright__ = '(C) 2023 by LibKDV Group'


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load FastDensityAnalysis class from file FastDensityAnalysis.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .fast_density_analysis import FastDensityAnalysisPlugin
    return FastDensityAnalysisPlugin(iface)
