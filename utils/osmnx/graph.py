"""Build a NetworkX graph from a local OSM-formatted XML file.

Slim build: only `graph_from_xml` is retained. The Overpass-driven
`graph_from_bbox`, `graph_from_point`, `graph_from_address`, `graph_from_place`,
and `graph_from_polygon` entry points have been removed because the host
plugin downloads OSM XML through its own Overpass client and only ever calls
into osmnx via the XML path.
"""

import itertools

import networkx as nx

from . import distance
from . import osm_xml
from . import settings
from . import simplification
from . import utils
from . import utils_graph
from ._errors import EmptyOverpassResponse
from ._version import __version__


def graph_from_xml(filepath, bidirectional=False, simplify=True, retain_all=False):
    """
    Create a graph from data in a .osm formatted XML file.

    Parameters
    ----------
    filepath : string or pathlib.Path
        path to file containing OSM XML data
    bidirectional : bool
        if True, create bi-directional edges for one-way streets
    simplify : bool
        if True, simplify graph topology with the `simplify_graph` function
    retain_all : bool
        if True, return the entire graph even if it is not connected.
        otherwise, retain only the largest weakly connected component.

    Returns
    -------
    G : networkx.MultiDiGraph
    """
    # transmogrify file of OSM XML data into JSON
    response_jsons = [osm_xml._overpass_json_from_file(filepath)]

    # create graph using this response JSON
    G = _create_graph(response_jsons, bidirectional=bidirectional, retain_all=retain_all)

    # simplify the graph topology as the last step
    if simplify:
        G = simplification.simplify_graph(G)

    utils.log(f"graph_from_xml returned graph with {len(G)} nodes and {len(G.edges)} edges")
    return G


def _create_graph(response_jsons, retain_all=False, bidirectional=False):
    """
    Create a networkx MultiDiGraph from Overpass API responses.

    Adds length attributes in meters (great-circle distance between endpoints)
    to all of the graph's (pre-simplified, straight-line) edges via the
    `distance.add_edge_lengths` function.

    Parameters
    ----------
    response_jsons : list
        list of dicts of JSON responses from from the Overpass API
    retain_all : bool
        if True, return the entire graph even if it is not connected.
        otherwise, retain only the largest weakly connected component.
    bidirectional : bool
        if True, create bi-directional edges for one-way streets

    Returns
    -------
    G : networkx.MultiDiGraph
    """
    utils.log("Creating graph from downloaded OSM data...")

    # make sure we got data back from the server request(s)
    if not any(rj["elements"] for rj in response_jsons):  # pragma: no cover
        msg = "There are no data elements in the server response. Check log and query location/filters."
        raise EmptyOverpassResponse(msg)

    # create the graph as a MultiDiGraph and set its meta-attributes
    metadata = {
        "created_date": utils.ts(),
        "created_with": f"OSMnx {__version__}",
        "crs": settings.default_crs,
    }
    G = nx.MultiDiGraph(**metadata)

    # extract nodes and paths from the downloaded osm data
    nodes = {}
    paths = {}
    for response_json in response_jsons:
        nodes_temp, paths_temp = _parse_nodes_paths(response_json)
        nodes.update(nodes_temp)
        paths.update(paths_temp)

    # add each osm node to the graph
    for node, data in nodes.items():
        G.add_node(node, **data)

    # add each osm way (ie, a path of edges) to the graph
    _add_paths(G, paths.values(), bidirectional)

    # retain only the largest connected component if retain_all is False
    if not retain_all:
        G = utils_graph.get_largest_component(G)

    utils.log(f"Created graph with {len(G)} nodes and {len(G.edges)} edges")

    # add length (great-circle distance between nodes) attribute to each edge
    if len(G.edges) > 0:
        G = distance.add_edge_lengths(G)

    return G


def _convert_node(element):
    """
    Convert an OSM node element into the format for a networkx node.

    Parameters
    ----------
    element : dict
        an OSM node element

    Returns
    -------
    node : dict
    """
    node = {"y": element["lat"], "x": element["lon"]}
    if "tags" in element:
        for useful_tag in settings.useful_tags_node:
            if useful_tag in element["tags"]:
                node[useful_tag] = element["tags"][useful_tag]
    return node


def _convert_path(element):
    """
    Convert an OSM way element into the format for a networkx path.

    Parameters
    ----------
    element : dict
        an OSM way element

    Returns
    -------
    path : dict
    """
    path = {"osmid": element["id"]}

    # remove any consecutive duplicate elements in the list of nodes
    path["nodes"] = [group[0] for group in itertools.groupby(element["nodes"])]

    if "tags" in element:
        for useful_tag in settings.useful_tags_way:
            if useful_tag in element["tags"]:
                path[useful_tag] = element["tags"][useful_tag]
    return path


def _parse_nodes_paths(response_json):
    """
    Construct dicts of nodes and paths from an Overpass response.

    Parameters
    ----------
    response_json : dict
        JSON response from the Overpass API

    Returns
    -------
    nodes, paths : tuple of dicts
        dicts' keys = osmid and values = dict of attributes
    """
    nodes = {}
    paths = {}
    for element in response_json["elements"]:
        if element["type"] == "node":
            nodes[element["id"]] = _convert_node(element)
        elif element["type"] == "way":
            paths[element["id"]] = _convert_path(element)

    return nodes, paths


def _is_path_one_way(path, bidirectional, oneway_values):
    """
    Determine if a path of nodes allows travel in only one direction.

    Parameters
    ----------
    path : dict
        a path's `tag:value` attribute data
    bidirectional : bool
        whether this is a bi-directional network type
    oneway_values : set
        the values OSM uses in its 'oneway' tag to denote True

    Returns
    -------
    bool
    """
    # rule 1
    if settings.all_oneway:
        # if globally configured to set every edge one-way, then it's one-way
        return True

    # rule 2
    elif bidirectional:
        # if this is a bi-directional network type, then nothing in it is
        # considered one-way. eg, if this is a walking network, this may very
        # well be a one-way street (as cars/bikes go), but in a walking-only
        # network it is a bi-directional edge (you can walk both directions on
        # a one-way street). so we will add this path (in both directions) to
        # the graph and set its oneway attribute to False.
        return False

    # rule 3
    elif "oneway" in path and path["oneway"] in oneway_values:
        # if this path is tagged as one-way and if it is not a bi-directional
        # network type then we'll add the path in one direction only
        return True

    # rule 4
    elif "junction" in path and path["junction"] == "roundabout":
        # roundabouts are also one-way but are not explicitly tagged as such
        return True

    else:
        # otherwise this path is not tagged as a one-way
        return False


def _is_path_reversed(path, reversed_values):
    """
    Determine if the order of nodes in a path should be reversed.

    Parameters
    ----------
    path : dict
        a path's `tag:value` attribute data
    reversed_values : set
        the values OSM uses in its 'oneway' tag to denote travel can only
        occur in the opposite direction of the node order

    Returns
    -------
    bool
    """
    if "oneway" in path and path["oneway"] in reversed_values:
        return True
    else:
        return False


def _add_paths(G, paths, bidirectional=False):
    """
    Add a list of paths to the graph as edges.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        graph to add paths to
    paths : list
        list of paths' `tag:value` attribute data dicts
    bidirectional : bool
        if True, create bi-directional edges for one-way streets

    Returns
    -------
    None
    """
    # the values OSM uses in its 'oneway' tag to denote True, and to denote
    # travel can only occur in the opposite direction of the node order. see:
    # https://wiki.openstreetmap.org/wiki/Key:oneway
    # https://www.geofabrik.de/de/data/geofabrik-osm-gis-standard-0.7.pdf
    oneway_values = {"yes", "true", "1", "-1", "reverse", "T", "F"}
    reversed_values = {"-1", "reverse", "T"}

    for path in paths:
        # extract/remove the ordered list of nodes from this path element so
        # we don't add it as a superfluous attribute to the edge later
        nodes = path.pop("nodes")

        # reverse the order of nodes in the path if this path is both one-way
        # and only allows travel in the opposite direction of nodes' order
        is_one_way = _is_path_one_way(path, bidirectional, oneway_values)
        if is_one_way and _is_path_reversed(path, reversed_values):
            nodes.reverse()

        # set the oneway attribute, but only if when not forcing all edges to
        # oneway with the all_oneway setting. With the all_oneway setting, you
        # want to preserve the original OSM oneway attribute for later clarity
        if not settings.all_oneway:
            path["oneway"] = is_one_way

        # zip path nodes to get (u, v) tuples like [(0,1), (1,2), (2,3)].
        edges = list(zip(nodes[:-1], nodes[1:]))

        # add all the edge tuples and give them the path's tag:value attrs
        path["reversed"] = False
        G.add_edges_from(edges, **path)

        # if the path is NOT one-way, reverse direction of each edge and add
        # this path going the opposite direction too
        if not is_one_way:
            path["reversed"] = True
            G.add_edges_from([(v, u) for u, v in edges], **path)
