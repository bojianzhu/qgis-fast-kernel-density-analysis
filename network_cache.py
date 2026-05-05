# -*- coding: utf-8 -*-
"""
Network Cache Module for Fast Density Analysis

This module provides caching functionality for road network data downloaded from
OpenStreetMap via Overpass API. It helps avoid repeated downloads of the same
road network data.

Features:
- Cache road network data with bounding box metadata
- Check if a requested bbox is contained within a cached bbox
- Automatic cache management
"""

import os
import json
import hashlib
import pickle
from datetime import datetime
from qgis.core import QgsProject

# =============================================================================
# DEBUG SETTINGS - Change these for debugging
# =============================================================================
# Set to False to disable cache and always download fresh data
ENABLE_CACHE = True

# Set to True to print detailed debug messages
DEBUG_MODE = False
# =============================================================================


class NetworkCache:
    """
    A class to manage road network caching.
    
    The cache is stored in the QGIS project's temp directory under 'network_cache/'.
    Each cached network is stored with:
    - A pickle file containing the processed graph
    - Metadata in a central JSON index file
    """
    
    # Margin to add when checking if bbox is contained (in degrees)
    # This allows for small variations in bbox
    BBOX_TOLERANCE = 0.01  # ~1000m at equator
    
    def __init__(self, feedback=None):
        """
        Initialize the NetworkCache.
        
        Args:
            feedback: QGIS feedback object for logging (optional)
        """
        self.feedback = feedback
        self.cache_dir = self._get_cache_dir()
        self.index_file = os.path.join(self.cache_dir, 'cache_index.json')
        self._ensure_cache_dir()
        self.index = self._load_index()
    
    def _log(self, message):
        """Log a message to feedback if available."""
        if self.feedback:
            self.feedback.pushInfo(message)
    
    def _get_cache_dir(self):
        """Get the cache directory path based on QGIS project location."""
        prj_path = QgsProject.instance().homePath()
        if not prj_path:
            # Fallback to user's home directory if no project is open
            prj_path = os.path.expanduser('~')
        # Normalize path for cross-platform compatibility
        return os.path.normpath(os.path.join(prj_path, 'temp', 'network_cache'))
    
    def _ensure_cache_dir(self):
        """Create cache directory if it doesn't exist."""
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception as e:
            self._log(f'Warning: Could not create cache directory: {e}')
    
    def _load_index(self):
        """Load the cache index from JSON file."""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self._log(f'Warning: Could not load cache index: {e}')
        return {'caches': []}
    
    def _save_index(self):
        """Save the cache index to JSON file."""
        try:
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(self.index, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._log(f'Warning: Could not save cache index: {e}')
    
    def _bbox_contains(self, outer_bbox, inner_bbox):
        """
        Check if outer_bbox contains inner_bbox.
        
        Args:
            outer_bbox: dict with keys 'lat_min', 'lat_max', 'lon_min', 'lon_max'
            inner_bbox: dict with same keys
            
        Returns:
            bool: True if outer contains inner (with tolerance)
        """
        tolerance = self.BBOX_TOLERANCE
        return (
            outer_bbox['lat_min'] - tolerance <= inner_bbox['lat_min'] and
            outer_bbox['lat_max'] + tolerance >= inner_bbox['lat_max'] and
            outer_bbox['lon_min'] - tolerance <= inner_bbox['lon_min'] and
            outer_bbox['lon_max'] + tolerance >= inner_bbox['lon_max']
        )
    
    def _generate_cache_id(self, bbox):
        """Generate a unique cache ID based on bbox."""
        bbox_str = f"{bbox['lat_min']:.6f}_{bbox['lat_max']:.6f}_{bbox['lon_min']:.6f}_{bbox['lon_max']:.6f}"
        return hashlib.md5(bbox_str.encode()).hexdigest()[:12]
    
    def find_suitable_cache(self, lat_min, lat_max, lon_min, lon_max):
        """
        Find a cached network that contains the requested bbox.
        
        Args:
            lat_min, lat_max, lon_min, lon_max: Requested bounding box
            
        Returns:
            dict or None: Cache entry if found, None otherwise
        """
        requested_bbox = {
            'lat_min': lat_min,
            'lat_max': lat_max,
            'lon_min': lon_min,
            'lon_max': lon_max
        }
        
        for cache_entry in self.index.get('caches', []):
            cached_bbox = cache_entry['bbox']
            cache_file = os.path.join(self.cache_dir, cache_entry['filename'])
            
            # Check if cache file still exists
            if not os.path.exists(cache_file):
                continue
                
            # Check if cached bbox contains requested bbox
            if self._bbox_contains(cached_bbox, requested_bbox):
                
                if DEBUG_MODE:
                    self._log(f'[DEBUG] Found suitable cache: {cache_entry["cache_id"]}')
                    self._log(f'[DEBUG]  Cached bbox: ({cached_bbox["lat_min"]:.4f}, {cached_bbox["lon_min"]:.4f}) to ({cached_bbox["lat_max"]:.4f}, {cached_bbox["lon_max"]:.4f})')
                    self._log(f'[DEBUG]  Requested bbox: ({lat_min:.4f}, {lon_min:.4f}) to ({lat_max:.4f}, {lon_max:.4f})')
                else:
                    self._log(f'Found suitable cache.')
                return cache_entry
        
        return None
    
    def load_cached_graph(self, cache_entry):
        """
        Load a cached graph from file.
        
        Args:
            cache_entry: Cache entry dict from find_suitable_cache()
            
        Returns:
            tuple: (graph, xml_content) or (None, None) if loading fails
        """
        cache_file = os.path.join(self.cache_dir, cache_entry['filename'])
        xml_file = os.path.join(self.cache_dir, cache_entry.get('xml_filename', ''))
        
        try:
            # Load the pickled graph
            with open(cache_file, 'rb') as f:
                graph = pickle.load(f)
            
            # Load XML content if exists
            xml_content = None
            if xml_file and os.path.exists(xml_file):
                with open(xml_file, 'r', encoding='utf-8') as f:
                    xml_content = f.read()
            if DEBUG_MODE:
                self._log(f'[DEBUG] Loaded cached graph with {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges')
            return graph, xml_content
            
        except Exception as e:
            self._log(f'Warning: Could not load cached graph: {e}')
            return None, None
    
    def save_to_cache(self, graph, xml_content, lat_min, lat_max, lon_min, lon_max):
        """
        Save a graph to cache.
        
        Args:
            graph: The processed networkx graph
            xml_content: The original OSM XML content
            lat_min, lat_max, lon_min, lon_max: Bounding box
            
        Returns:
            str: Cache ID of the saved cache
        """
        bbox = {
            'lat_min': lat_min,
            'lat_max': lat_max,
            'lon_min': lon_min,
            'lon_max': lon_max
        }
        
        cache_id = self._generate_cache_id(bbox)
        graph_filename = f'graph_{cache_id}.pkl'
        xml_filename = f'osm_{cache_id}.xml'
        
        graph_file = os.path.join(self.cache_dir, graph_filename)
        xml_file = os.path.join(self.cache_dir, xml_filename)
        
        try:
            # Save the graph (use protocol 4 for Python 3.4+ compatibility)
            with open(graph_file, 'wb') as f:
                pickle.dump(graph, f, protocol=4)
            
            # Save XML content
            if xml_content:
                with open(xml_file, 'w', encoding='utf-8') as f:
                    f.write(xml_content)
            
            # Add to index
            cache_entry = {
                'cache_id': cache_id,
                'bbox': bbox,
                'filename': graph_filename,
                'xml_filename': xml_filename,
                'created': datetime.now().isoformat(),
                'nodes': graph.number_of_nodes(),
                'edges': graph.number_of_edges()
            }
            
            # Remove any existing cache with same ID
            self.index['caches'] = [c for c in self.index.get('caches', []) if c['cache_id'] != cache_id]
            self.index['caches'].append(cache_entry)
            self._save_index()
            if DEBUG_MODE:
                self._log(f'[DEBUG] Saved network to cache: {cache_id}')
                self._log(f'[DEBUG]  Bbox: ({lat_min:.4f}, {lon_min:.4f}) to ({lat_max:.4f}, {lon_max:.4f})')
                self._log(f'[DEBUG]  Graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges')
            
            return cache_id
            
        except Exception as e:
            self._log(f'Warning: Could not save to cache: {e}')
            return None
    
    # ------------------------------------------------------------------
    # Preprocess artifact cache (NKDV intermediate products that depend
    # only on the graph, not on the input points).
    # ------------------------------------------------------------------
    def get_preproc_paths(self, cache_id, lixel_length=None, points_hash=None,
                          temporal_hash=None):
        """Return a dict of paths for preprocess artifacts of a cache_id.

        Items:
          - 'edges_pkl'        : pickled edge dataframe (u_id, v_id, length)
          - 'simplified_gpkg'  : geometry-only edges geopackage
          - 'split_geojson'    : edges split by lixel_length (only if given)
          - 'graph_output'     : NKDV graph_output text (projected points +
                                 merged distances), keyed by (cache_id, points_hash)
          - 'graph_output_t'   : NTKDV graph_output text (with timestamps),
                                 keyed by (cache_id, temporal_hash)
        """
        d = self.cache_dir
        paths = {
            'edges_pkl':       os.path.join(d, f'edges_{cache_id}.pkl'),
            'simplified_gpkg': os.path.join(d, f'simplified_{cache_id}.gpkg'),
        }
        if lixel_length is not None:
            paths['split_geojson'] = os.path.join(
                d, f'split_{cache_id}_lixel{lixel_length}.geojson'
            )
        if points_hash is not None:
            paths['graph_output'] = os.path.join(
                d, f'graphout_{cache_id}_{points_hash}.txt'
            )
        if temporal_hash is not None:
            paths['graph_output_t'] = os.path.join(
                d, f'graphout_t_{cache_id}_{temporal_hash}.txt'
            )
        return paths

    def has_graph_preproc(self, cache_id):
        """True if the graph-only preproc artifacts exist for this cache_id."""
        p = self.get_preproc_paths(cache_id)
        return os.path.exists(p['edges_pkl']) and os.path.exists(p['simplified_gpkg'])

    def has_split(self, cache_id, lixel_length):
        """True if the split-by-lixel artifact exists for this (cache_id, lixel)."""
        p = self.get_preproc_paths(cache_id, lixel_length)
        return os.path.exists(p['split_geojson'])

    def has_graph_output(self, cache_id, points_hash):
        """True if the projected-points graph_output exists for this (cache_id, points_hash)."""
        p = self.get_preproc_paths(cache_id, points_hash=points_hash)
        return os.path.exists(p['graph_output'])

    def has_graph_output_t(self, cache_id, temporal_hash):
        """True if the temporal projected-points graph_output exists."""
        p = self.get_preproc_paths(cache_id, temporal_hash=temporal_hash)
        return os.path.exists(p['graph_output_t'])

    @staticmethod
    def hash_points(coor_list):
        """Stable fingerprint of an input point set.

        Tolerates tiny floating-point drift (rounded to 8 decimals, ~1mm at
        the equator) and is invariant to ordering.
        """
        import numpy as np
        arr = np.asarray(coor_list, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] < 2:
            arr = arr.reshape(-1, 2)
        arr = np.round(arr[:, :2], decimals=8)
        arr = arr[np.lexsort((arr[:, 1], arr[:, 0]))]
        return hashlib.md5(arr.tobytes()).hexdigest()[:12]

    @staticmethod
    def hash_points_with_time(coor_list, time_list):
        """Stable fingerprint of (lon, lat, time) triples for NTKDV.

        time_list values are rounded to 6 decimals (~0.1s precision when
        time is in days), and the rows are lexically sorted so the hash
        is invariant to point ordering.
        """
        import numpy as np
        coor = np.asarray(coor_list, dtype=np.float64).reshape(-1, 2)
        tarr = np.asarray(time_list, dtype=np.float64).reshape(-1, 1)
        if coor.shape[0] != tarr.shape[0]:
            raise ValueError(
                'coor_list and time_list must have the same length '
                f'({coor.shape[0]} vs {tarr.shape[0]})'
            )
        coor = np.round(coor, decimals=8)
        tarr = np.round(tarr, decimals=6)
        arr = np.hstack([coor, tarr])
        arr = arr[np.lexsort((arr[:, 2], arr[:, 1], arr[:, 0]))]
        return hashlib.md5(arr.tobytes()).hexdigest()[:12]

    def clear_cache(self):
        """Clear all cached networks."""
        try:
            for cache_entry in self.index.get('caches', []):
                graph_file = os.path.join(self.cache_dir, cache_entry['filename'])
                xml_file = os.path.join(self.cache_dir, cache_entry.get('xml_filename', ''))
                
                if os.path.exists(graph_file):
                    os.remove(graph_file)
                if xml_file and os.path.exists(xml_file):
                    os.remove(xml_file)
            
            self.index = {'caches': []}
            self._save_index()
            self._log('Cache cleared successfully')
            
        except Exception as e:
            self._log(f'Warning: Could not clear cache: {e}')
    
    def get_cache_info(self):
        """
        Get information about all cached networks.
        
        Returns:
            list: List of cache info dicts
        """
        info = []
        for cache_entry in self.index.get('caches', []):
            cache_file = os.path.join(self.cache_dir, cache_entry['filename'])
            size = 0
            if os.path.exists(cache_file):
                size = os.path.getsize(cache_file) / (1024 * 1024)  # MB
            
            info.append({
                'cache_id': cache_entry['cache_id'],
                'bbox': cache_entry['bbox'],
                'nodes': cache_entry.get('nodes', 'N/A'),
                'edges': cache_entry.get('edges', 'N/A'),
                'created': cache_entry.get('created', 'N/A'),
                'size_mb': round(size, 2)
            })
        return info


def download_and_cache_network(lat_min, lat_max, lon_min, lon_max, folder_path, feedback=None):
    """
    Download road network from OSM or load from cache.
    
    This is a convenience function that handles the full workflow:
    1. Check if a suitable cache exists
    2. If yes, load from cache
    3. If no, download from Overpass API and cache the result
    
    Args:
        lat_min, lat_max, lon_min, lon_max: Bounding box
        folder_path: Path for temporary files
        feedback: QGIS feedback object
        
    Returns:
        tuple: (processed_graph, xml_file_path, from_cache, cache_id)
            cache_id identifies the bbox-key for this graph -- callers can
            use it to cache further preprocessing artifacts that depend
            only on the graph (e.g. edge dataframe, split lines).
    """
    from .utils.overpass import API
    from .utils import osmnx as ox
    import networkx as nx
    import time

    cache = NetworkCache(feedback)

    # Normalize folder_path for cross-platform compatibility
    folder_path = os.path.normpath(folder_path)

    # Ensure folder_path exists
    os.makedirs(folder_path, exist_ok=True)

    # Check cache if enabled
    cache_entry = None
    if ENABLE_CACHE:
        cache_entry = cache.find_suitable_cache(lat_min, lat_max, lon_min, lon_max)
        if DEBUG_MODE:
            feedback.pushInfo(f'[DEBUG] ENABLE_CACHE={ENABLE_CACHE}, cache_entry found={cache_entry is not None}')
    else:
        feedback.pushInfo('Cache is DISABLED (ENABLE_CACHE=False)')

    if cache_entry:
        graph, xml_content = cache.load_cached_graph(cache_entry)
        if graph is not None:
            xml_path = os.path.join(folder_path, "testio.xml")
            if xml_content:
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(xml_content)
            return graph, xml_path, True, cache_entry['cache_id']
    
    # Download from Overpass API
    start = time.time()

    bbox_str = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    query = f"""
    (
    way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|living_street|unclassified|service|road)$"]({bbox_str});
    );
    (._;>;);
    out body;
        """

    # Use longer timeout and retry mechanism
    max_retries = 5
    xml_content = None
    last_error = None
    download_dur = 0.0
    xml_size_mb = 0.0

    for attempt in range(max_retries):
        attempt_start = time.time()
        try:
            api = API(timeout=180)
            xml_content = api.get(query, verbosity='body', responseformat='xml')
            download_dur = time.time() - attempt_start
            xml_size_mb = len(xml_content) / (1024 * 1024) if xml_content else 0
            break
        except Exception as e:
            last_error = e
            feedback.pushInfo('  [attempt {}/{}] failed in {:.1f}s: {}'.format(
                attempt + 1, max_retries, time.time() - attempt_start, str(e)))
            if attempt < max_retries - 1:
                import time as time_module
                time_module.sleep(2)
        if feedback.isCanceled():
            raise Exception('Cancelled by user during download.')

    if xml_content is None:
        raise Exception(f'Failed to download road network after {max_retries} attempts. Last error: {last_error}')

    xml_path = os.path.join(folder_path, "testio.xml")
    with open(xml_path, mode="w", encoding='utf-8') as f:
        f.write(xml_content)

    t_parse = time.time()
    g1 = ox.graph_from_xml(xml_path, simplify=False)
    parse_dur = time.time() - t_parse

    t_proj = time.time()
    g1_projected = ox.project_graph(g1)
    proj_dur = time.time() - t_proj

    t_cons = time.time()
    gc1_projected = ox.consolidate_intersections(g1_projected, tolerance=5, rebuild_graph=True)
    cons_dur = time.time() - t_cons
    if DEBUG_MODE:
        feedback.pushInfo(f'[DEBUG] After consolidation: {gc1_projected.number_of_nodes()} nodes, {gc1_projected.number_of_edges()} edges')
    
    # Convert to undirected MultiGraph while preserving ALL edge attributes
    # We manually convert to avoid losing geometry attribute
    undi_gc1 = gc1_projected.to_undirected()
    
    # Create a new MultiGraph and manually copy edges with all attributes
    g_projected = nx.MultiGraph()
    g_projected.graph.update(gc1_projected.graph)  # Copy graph attributes (CRS, etc.)
    
    # Copy nodes with all attributes
    for node, data in undi_gc1.nodes(data=True):
        g_projected.add_node(node, **data)
    
    # Copy edges - for each pair of nodes, keep only one edge but preserve all attributes
    seen_edges = set()
    for u, v, key, data in undi_gc1.edges(keys=True, data=True):
        edge_pair = tuple(sorted([u, v]))
        if edge_pair not in seen_edges:
            seen_edges.add(edge_pair)
            g_projected.add_edge(u, v, **data)
    if DEBUG_MODE:
        feedback.pushInfo(f'[DEBUG] Converted to undirected: {g_projected.number_of_nodes()} nodes, {g_projected.number_of_edges()} edges')
    
    # Check if geometry is preserved
    sample_edge = list(g_projected.edges(data=True))[0] if g_projected.number_of_edges() > 0 else None
    if sample_edge and 'geometry' in sample_edge[2]:
        if DEBUG_MODE:
            feedback.pushInfo(f'[DEBUG] Geometry attribute preserved: YES')
    else:
        if DEBUG_MODE:
            feedback.pushInfo(f'[DEBUG] WARNING: Geometry attribute may be missing!')
            # Try to add geometry from coordinates if missing
        if DEBUG_MODE:
            feedback.pushInfo(f'[DEBUG] Attempting to add geometry from node coordinates...')
        from shapely.geometry import LineString
        for u, v, key, data in g_projected.edges(keys=True, data=True):
            if 'geometry' not in data:
                u_data = g_projected.nodes[u]
                v_data = g_projected.nodes[v]
                if 'x' in u_data and 'y' in u_data and 'x' in v_data and 'y' in v_data:
                    line = LineString([(u_data['x'], u_data['y']), (v_data['x'], v_data['y'])])
                    data['geometry'] = line
        if DEBUG_MODE:
            feedback.pushInfo(f'[DEBUG] Geometry added from node coordinates')

    
    # IMPORTANT: Keep the graph in UTM projection for correct distance calculations!
    # Do NOT project back to EPSG:4326 here.
    # The C++ code needs distances in meters, not degrees.
    g = g_projected
    if DEBUG_MODE:
        feedback.pushInfo(f'[DEBUG]  Graph kept in UTM projection (CRS: {g.graph.get("crs", "unknown")})')
    
    # Edge lengths are already in meters (UTM), but ensure they exist
    g = ox.distance.add_edge_lengths(g)
    if DEBUG_MODE:
        feedback.pushInfo(f'[DEBUG] Edge lengths verified (in meters)')
    
    end = time.time()
    if DEBUG_MODE:
        feedback.pushInfo(f'[DEBUG] Download and processing completed in {end - start:.2f}s')
    if DEBUG_MODE:
        feedback.pushInfo(f'[DEBUG] Nodes: {g.number_of_nodes()}, Edges: {g.number_of_edges()}')
    
    # Save to cache if enabled
    cache_id = None
    if ENABLE_CACHE:
        cache_id = cache.save_to_cache(g, xml_content, lat_min, lat_max, lon_min, lon_max)
    else:
        if DEBUG_MODE:
            feedback.pushInfo('[DEBUG] Cache saving skipped (ENABLE_CACHE=False)')
    if cache_id is None:
        # Even with cache disabled, return a stable id so callers can still
        # store / retrieve preprocess artifacts deterministically.
        cache_id = cache._generate_cache_id({
            'lat_min': lat_min, 'lat_max': lat_max,
            'lon_min': lon_min, 'lon_max': lon_max,
        })

    return g, xml_path, False, cache_id

