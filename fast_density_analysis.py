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
import sys
import inspect
from qgis.PyQt.QtWidgets import QMenu, QToolButton
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication
from .fast_density_analysis_provider import FastDensityAnalysisProvider
import processing

cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]

if cmd_folder not in sys.path:
    sys.path.insert(0, cmd_folder)


class FastDensityAnalysisPlugin(object):

    def __init__(self, iface):
        self.iface = iface
        self.provider = FastDensityAnalysisProvider()

    def initProcessing(self):
        """Init Processing provider for QGIS >= 3.8."""

        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.toolbar = self.iface.addToolBar('Fast Density Analysis Toolbar')
        self.toolbar.setObjectName('FastDensityAnalysisToolbar')
        self.toolbar.setToolTip('Fast Density Analysis Toolbar')

        # Create the KDV menu items
        menu = QMenu()
        icon = QIcon(os.path.join(os.path.dirname(__file__), 'icons/kdv.png'))
        self.kdvAction = menu.addAction(icon, 'Kernel density visualization', self.kdvAlgorithm)
        self.iface.addPluginToMenu("Fast density analysis", self.kdvAction)

        icon = QIcon(os.path.join(os.path.dirname(__file__), 'icons/stkdv.png'))
        self.stkdvAction = menu.addAction(icon, 'Spatiotemporal KDV', self.stkdvAlgorithm)
        self.iface.addPluginToMenu("Fast density analysis", self.stkdvAction)

        icon = QIcon(os.path.join(os.path.dirname(__file__), 'icons/nkdv.png'))
        self.nkdvAction = menu.addAction(icon, 'Network KDV', self.nkdvAlgorithm)
        self.iface.addPluginToMenu("Fast density analysis", self.nkdvAction)

        # Add the KDV algorithms to the toolbar
        icon = QIcon(os.path.join(os.path.dirname(__file__), 'icons/fda.png'))
        self.kdvsButton = QToolButton()
        self.kdvsButton.setMenu(menu)
        self.kdvsButton.setPopupMode(QToolButton.MenuButtonPopup)
        self.kdvsButton.setDefaultAction(self.kdvAction)
        self.kdvsButton.setIcon(icon)
        self.kdvsToolbar = self.toolbar.addWidget(self.kdvsButton)

        self.initProcessing()

    def unload(self):
        self.iface.removePluginMenu('Fast density analysis', self.kdvAction)
        self.iface.removePluginMenu('Fast density analysis', self.stkdvAction)
        self.iface.removePluginMenu('Fast density analysis', self.nkdvAction)
        self.iface.removeToolBarIcon(self.kdvsToolbar)
        del self.toolbar
        QgsApplication.processingRegistry().removeProvider(self.provider)

    def kdvAlgorithm(self):
        processing.execAlgorithmDialog('fastdensityanalysis:kerneldensityvisualization(KDV)', {})

    def stkdvAlgorithm(self):
        processing.execAlgorithmDialog('fastdensityanalysis:spatiotemporalkdv(STKDV)', {})

    def nkdvAlgorithm(self):
        processing.execAlgorithmDialog('fastdensityanalysis:networkkdv(NKDV)', {})
