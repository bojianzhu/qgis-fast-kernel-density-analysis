"""Public API for the slim osmnx bundle.

This re-exports only the entry points the host plugin actually calls:

  - ``ox.graph_from_xml``
  - ``ox.project_graph``
  - ``ox.consolidate_intersections``
  - ``ox.nearest_edges``
  - ``ox.save_graph_geopackage``
  - ``ox.distance.add_edge_lengths`` (via the ``distance`` submodule, which is
    populated automatically by these imports)

All other osmnx helpers (folium/matplotlib plotting, Overpass downloader,
geocoder, geometries, elevation, speed, bearing, stats beyond the two
internally-used helpers, etc.) have been removed in this build.
"""

from .distance import nearest_edges
from .graph import graph_from_xml
from .io import save_graph_geopackage
from .projection import project_graph
from .simplification import consolidate_intersections
