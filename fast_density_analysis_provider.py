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
from qgis.core import QgsProcessingProvider
from .kdvAlgorithm import KDVAlgorithm
from .stkdvAlgorithm import STKDVAlgorithm
from qgis.PyQt.QtGui import QIcon

class FastDensityAnalysisProvider(QgsProcessingProvider):

    def __init__(self):
        """
        Default constructor.
        """
        QgsProcessingProvider.__init__(self)

    def unload(self):
        """
        Unloads the provider. Any tear-down steps required by the provider
        should be implemented here.
        """
        QgsProcessingProvider.unload(self)

    def loadAlgorithms(self):
        """
        Loads all algorithms belonging to this provider.
        """
        self.addAlgorithm(KDVAlgorithm())
        self.addAlgorithm(STKDVAlgorithm())


    def id(self):
        """
        Returns the unique provider id, used for identifying the provider. This
        string should be a unique, short, character only string, eg "qgis" or
        "gdal". This string should not be localised.
        """
        return 'fastdensityanalysis'

    def name(self):
        """
        Returns the provider name, which is used to describe the provider
        within the GUI.

        This string should be short (e.g. "Lastools") and localised.
        """
        return self.tr('Fast density analysis')

    def icon(self):
        """
        Should return a QIcon which is used for your provider inside
        the Processing toolbox.
        """
        return QIcon(os.path.join(os.path.dirname(__file__), 'icons/fda.png'))

    def longName(self):
        """
        Returns the a longer version of the provider name, which can include
        extra details such as version numbers. E.g. "Lastools LIDAR tools
        (version 2.2.1)". This string should be localised. The default
        implementation returns the same string as name().
        """
        return self.name()
