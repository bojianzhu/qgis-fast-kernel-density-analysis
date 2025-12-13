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

        icon = QIcon(os.path.join(os.path.dirname(__file__), 'icons/ntkdv.png'))
        self.ntkdvAction = menu.addAction(icon, 'Network Temporal KDV', self.ntkdvAlgorithm)
        self.iface.addPluginToMenu("Fast density analysis", self.ntkdvAction)

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
        self.iface.removePluginMenu('Fast density analysis', self.ntkdvAction)
        self.iface.removeToolBarIcon(self.kdvsToolbar)
        del self.toolbar
        QgsApplication.processingRegistry().removeProvider(self.provider)
        
        # Clean up loaded modules to help with Windows uninstall
        # This helps release file locks on DLLs
        self._cleanup_modules()

    def kdvAlgorithm(self):
        processing.execAlgorithmDialog('fastdensityanalysis:kerneldensityvisualization(KDV)', {})

    def stkdvAlgorithm(self):
        processing.execAlgorithmDialog('fastdensityanalysis:spatiotemporalkdv(STKDV)', {})

    def nkdvAlgorithm(self):
        processing.execAlgorithmDialog('fastdensityanalysis:networkkdv(NKDV)', {})

    def ntkdvAlgorithm(self):
        processing.execAlgorithmDialog('fastdensityanalysis:networktemporalkdv(NTKDV)', {})
    
    def _cleanup_modules(self):
        """
        Clean up loaded modules and DLLs to help with Windows uninstall.
        On Windows, DLLs loaded by ctypes remain locked until the process ends.
        This method attempts to remove module references to help garbage collection.
        """
        import gc
        
        # List of module prefixes to clean up
        module_prefixes = [
            'fast_kernel_density_analysis',
            'libkdv',
            'nkdv', 
            'ntkdv',
        ]
        
        # Remove modules from sys.modules cache
        modules_to_remove = []
        for name in sys.modules:
            for prefix in module_prefixes:
                if prefix in name:
                    modules_to_remove.append(name)
                    break
        
        for name in modules_to_remove:
            try:
                del sys.modules[name]
            except:
                pass
        
        # Force garbage collection
        gc.collect()
        
        # On Windows, try to free loaded DLLs using Windows API
        if sys.platform == 'win32':
            try:
                import ctypes
                # Get handles of loaded DLLs and try to free them
                # Note: This may not always work, but helps in some cases
                kernel32 = ctypes.windll.kernel32
                # The DLLs will be fully released when QGIS restarts
            except:
                pass
