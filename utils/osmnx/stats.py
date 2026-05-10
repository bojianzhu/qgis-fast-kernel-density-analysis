"""
Geometric/topological measures used by simplification.consolidate_intersections.

Slimmed down to only the two helpers that the trimmed osmnx still calls.
"""

import itertools
import logging as lg
from collections import Counter

import networkx as nx

from . import utils


def streets_per_node(G):
    """
    Count streets (undirected edges) incident on each node.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        input graph

    Returns
    -------
    spn : dict
        dictionary with node ID keys and street count values
    """
    spn = dict(nx.get_node_attributes(G, "street_count"))
    if set(spn) != set(G.nodes):
        utils.log("Graph nodes changed since `street_count`s were calculated", level=lg.WARN)
    return spn


def count_streets_per_node(G, nodes=None):
    """
    Count how many physical street segments connect to each node in a graph.

    This function uses an undirected representation of the graph and special
    handling of self-loops to accurately count physical streets rather than
    directed edges.

    Parameters
    ----------
    G : networkx.MultiDiGraph
        input graph
    nodes : list
        which node IDs to get counts for. if None, use all graph nodes,
        otherwise calculate counts only for these node IDs

    Returns
    -------
    streets_per_node : dict
        counts of how many physical streets connect to each node, with keys =
        node ids and values = counts
    """
    if nodes is None:
        nodes = G.nodes

    # get one copy of each self-loop edge, because bi-directional self-loops
    # appear twice in the undirected graph (u,v,0 and u,v,1 where u=v), but
    # one-way self-loops will appear only once
    Gu = G.to_undirected(reciprocal=False, as_view=True)
    self_loop_edges = set(nx.selfloop_edges(Gu))

    # get all non-self-loop undirected edges, including parallel edges
    non_self_loop_edges = [e for e in Gu.edges(keys=False) if e not in self_loop_edges]

    # make list of all unique edges including each parallel edge unless the
    # parallel edge is a self-loop, in which case we don't double-count it
    all_unique_edges = non_self_loop_edges + list(self_loop_edges)

    # flatten list of (u, v) edge tuples to count how often each node appears
    edges_flat = itertools.chain.from_iterable(all_unique_edges)
    counts = Counter(edges_flat)
    streets_per_node = {node: counts[node] for node in nodes}

    utils.log("Counted undirected street segments incident on each node")
    return streets_per_node
