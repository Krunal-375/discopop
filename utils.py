from typing import List, Set

import numpy as np
from graph_tool.all import Vertex, Graph, Edge


loop_data = {}


def correlation_coefficient(v1: List[float], v2: List[float]) -> float:
    """Calculates correlation coefficient as (A dot B) / (norm(A) * norm(B))

    :param v1: first vector
    :param v2: second vector
    :return: correlation coefficient, 0 if one of the norms is 0
    """
    norm_product = np.linalg.norm(v1) * np.linalg.norm(v2)
    return 0 if norm_product == 0 else np.dot(v1, v2) / norm_product


def find_subnodes(graph: Graph, node: Vertex, criteria: str) -> List[Vertex]:
    """Returns direct children of a given node

    :param graph: CU graph
    :param node: node
    :param criteria: type of dependency
    :return: list of children nodes
    """
    return [e.target() for e in node.out_edges() if graph.ep.type[e] == criteria]


def depends(graph: Graph, source: Vertex, target: Vertex) -> bool:
    """Detects if source node or one of it's children has a RAW dependency to target node or one of it's children

    :param graph: CU graph
    :param source: source node for dependency detection
    :param target: target of dependency
    :return: true, if there is RAW dependency
    """
    if source == target:
        return False
    target_nodes = get_subtree_of_type(graph, target, '*')

    for node in get_subtree_of_type(graph, source, '*'):
        for dep in [e.target() for e in node.out_edges() if graph.ep.dtype[e] == 'RAW']:
            if dep in target_nodes:
                return True
    return False


def depends_ignore_readonly(graph: Graph, source: Vertex, target: Vertex, root_loop: Vertex) -> bool:
    """Detects if source node or one of it's children has a RAW dependency to target node or one of it's children
    The loop index and readonly variables are ignored

    :param graph: CU graph
    :param source: source node for dependency detection
    :param target: target of dependency
    :param root_loop: root loop
    :return: true, if there is RAW dependency
    """
    children = get_subtree_of_type(graph, target, 'cu')
    children.append(target)

    for dep in get_all_dependencies(graph, source, root_loop):
        if dep in children:
            return True
    return False


def is_loop_index(graph: Graph, edge: Edge, loops_start_lines: List[str], children: List[Vertex]) -> bool:
    """Checks, whether the variable is a loop index.

    :param graph: CU graph
    :param edge: RAW dependency
    :param loops_start_lines: start lines of the loops
    :param children: children nodes of the loops
    :return: true if edge represents loop index
    """

    # TODO check all dependencies necessary?
    # If there is a raw dependency for var, the source cu is part of the loop
    # and the dependency occurs in loop header, then var is loop index+
    return (graph.ep.source[edge] == graph.ep.sink[edge]
            and graph.ep.source[edge] in loops_start_lines
            and edge.target() in children)


def is_readonly_inside_loop_body(graph: Graph, dep: Edge, root_loop: Vertex) -> bool:
    """Checks, whether a variable is read-only in loop body

    :param graph: CU graph
    :param dep: dependency variable
    :param root_loop: root loop
    :return: true if variable is read-only in loop body
    """
    loops_start_lines = [graph.vp.startsAtLine[v]
                         for v in get_subtree_of_type(graph, root_loop, 'loop')]

    children = get_subtree_of_type(graph, root_loop, 'cu')

    for v in children:
        for e in v.out_edges():
            # If there is a waw dependency for var, then var is written in loop
            # (sink is always inside loop for waw/war)
            if graph.ep.dtype[e] == 'WAR' or graph.ep.dtype[e] == 'WAW':
                if (graph.ep.var[dep] == graph.ep.var[e]
                        and not (graph.ep.sink[e] in loops_start_lines)):
                    return False
        for e in v.in_edges():
            # If there is a reverse raw dependency for var, then var is written in loop
            # (source is always inside loop for reverse raw)
            if graph.ep.dtype[e] == 'RAW':
                if (graph.ep.var[dep] == graph.ep.var[e]
                        and not (graph.ep.source[e] in loops_start_lines)):
                    return False
    return True


def get_all_dependencies(graph: Graph, node: Vertex, root_loop: Vertex) -> Set[Vertex]:
    """Returns all data dependencies of the node and it's children
    This method ignores loop index and read only variables

    :param graph: CU graph
    :param node: node
    :param root_loop: root loop
    :return: list of all RAW dependencies of the node
    """
    dep_set = set()
    children = get_subtree_of_type(graph, node, 'cu')

    loops_start_lines = [graph.vp.startsAtLine[v]
                         for v in get_subtree_of_type(graph, root_loop, 'loop')]

    for v in children:
        for e in v.out_edges():
            if graph.ep.type[e] == 'dependence' and graph.ep.dtype[e] == 'RAW':
                if not (is_loop_index(graph, e, loops_start_lines, get_subtree_of_type(graph, root_loop, 'cu'))
                        and is_readonly_inside_loop_body(graph, e, root_loop)):
                    dep_set.add(e.target())
    return dep_set


# TODO set or list?
def get_subtree_of_type(graph: Graph, root: Vertex, node_type: str) -> List[Vertex]:
    """Returns all nodes of a given type from a subtree

    :param graph: CU graph
    :param root: root node
    :param node_type: specific type of nodes or '*' for wildcard
    :return: list of nodes of specified type from subtree
    """
    res = []
    if graph.vp.type[root] == node_type or node_type == '*':
        res.append(root)

    for e in root.out_edges():
        if graph.ep.type[e] == 'child':
            res.extend(get_subtree_of_type(graph, e.target(), node_type))
    return res


def find_main_node(graph: Graph) -> Vertex:
    """Return main node of the graph

    :param graph: CU graph
    :return: main node
    """
    for node in graph.vertices():
        if graph.vp.name[node] == 'main':
            return node


def total_instructions_count(graph: Graph, root: Vertex) -> int:
    """Calculates total number of the instructions in the subtree of a given node

    :param graph: CU graph
    :param root: root node
    :return: number of instructions
    """
    res = 0
    for node in get_subtree_of_type(graph, root, 'cu'):
        r = graph.vp.instructionsCount[node]
        i = graph.vp.id[node]
        res += graph.vp.instructionsCount[node]
    return res


def calculate_workload(graph: Graph, node: Vertex) -> int:
    """Calculates workload for a given node

    :param graph: CU graph
    :param node: root node
    :return: workload
    """
    res = 0
    if graph.vp.instructionsCount[node] == 'dummy':
        return 0
    elif graph.vp.instructionsCount[node] == 'cu':
        res += graph.vp.instructionsCount[node]
    elif graph.vp.instructionsCount[node] == 'func':
        for child in find_subnodes(graph, node, 'child'):
            res += calculate_workload(graph, child)
    elif graph.vp.instructionsCount[node] == 'loop':
        for child in get_subtree_of_type(graph, node, 'cu'):
            if 'for.inc' in graph.vp.BasicBlockID[child]:
                res += graph.vp.instructionsCount[node]
            elif 'for.cond' in graph.vp.BasicBlockID[child]:
                res += graph.vp.instructionsCount[node] * (get_loop_iterations(graph.vp.startsAtLine[node]) + 1)
            else:
                res += graph.vp.instructionsCount[node] * get_loop_iterations(graph.vp.startsAtLine[node])
    return res


def get_loop_iterations(line: str) -> int:
    """Calculates the number of iterations in specified loop

    :param line: start line of the loop
    :return: number of iterations
    """
    return loop_data.get(line, 0)
