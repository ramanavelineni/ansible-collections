# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""How the workflow module decides that a declared graph is the stored one, and what it sends when it is not.

The keys a task gives its nodes are not stored, so "unchanged" means: every
declared node can be paired with a stored node whose fields agree, and the
edges agree between the paired nodes. Stored graphs here are written by hand
in the shape of the public API description (WorkflowNode, WorkflowEdge).
"""

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.workflow import (
    desired_edge,
    desired_node,
    edge_view,
    graph_body,
    match_graph,
    node_view,
    stored_key,
    validate_graph,
)

TEMPLATES = {10: 'build', 11: 'deploy', 12: 'rollback'}
TEMPLATE_IDS = dict((name, tid) for tid, name in TEMPLATES.items())


def node(key, **fields):
    full = dict((k, None) for k in ('kind', 'template', 'convergence_mode', 'approval_timeout', 'approval_message',
                                    'delay_seconds', 'note', 'position_x', 'position_y', 'task_params', 'survey_inputs'))
    full.update(fields, key=key)
    return desired_node(full)


def edge(source, destination, **fields):
    full = dict(condition=None, input_mode=None, input_mappings=None)
    full.update(fields, source=source, destination=destination)
    return desired_edge(full)


# A stored release workflow: build (31) -> sign-off (32) -> deploy (33), and deploy -on_failure-> rollback (34).
STORED_NODES = [
    dict(id=33, kind='task', template_id=11, convergence_mode='all', position_x=600),
    dict(id=31, kind='task', template_id=10, convergence_mode='all',
         task_params=dict(environment='{"release": "1.0"}', message='nightly')),
    dict(id=34, kind='task', template_id=12, convergence_mode='all', position_x=900, position_y=150),
    dict(id=32, kind='approval', approval_message='Go on?', approval_timeout=3600, position_x=300),
]
STORED_EDGES = [
    dict(id=1, source_node_id=31, destination_node_id=32, condition='on_success', input_mode='by_name'),
    dict(id=2, source_node_id=32, destination_node_id=33, condition='on_success', input_mode='by_name'),
    dict(id=3, source_node_id=33, destination_node_id=34, condition='on_failure', input_mode='by_name'),
]

RELEASE_NODES = [
    node('build', template='build', task_params=dict(variables={'release': '1.0'})),
    node('sign-off', kind='approval', approval_message='Go on?'),
    node('deploy', template='deploy'),
    node('rollback', template='rollback'),
]
RELEASE_EDGES = [
    edge('build', 'sign-off', condition='on_success'),
    edge('sign-off', 'deploy'),
    edge('deploy', 'rollback', condition='on_failure'),
]


def stored(nodes=None, edges=None):
    nodes = STORED_NODES if nodes is None else nodes
    edges = STORED_EDGES if edges is None else edges
    views = [node_view(n, TEMPLATES) for n in nodes]
    keys = dict((n['id'], stored_key(n['id'])) for n in nodes)
    return views, [edge_view(e, keys) for e in edges]


def test_the_stored_graph_in_another_order_is_paired_node_by_node():
    pairing = match_graph(RELEASE_NODES, RELEASE_EDGES, *stored())
    assert pairing == {'build': 31, 'sign-off': 32, 'deploy': 33, 'rollback': 34}


def test_fields_a_node_leaves_out_do_not_stop_the_pairing():
    # deploy and rollback set no convergence_mode or position; the stored ones have them.
    assert match_graph(RELEASE_NODES, RELEASE_EDGES, *stored()) is not None


@pytest.mark.parametrize('nodes, edges, why', [
    ([node('build', template='build'), node('sign-off', kind='approval'), node('deploy', template='rollback'),
      node('rollback', template='rollback')], RELEASE_EDGES, 'a node runs another template'),
    (RELEASE_NODES, [edge('build', 'sign-off'), edge('sign-off', 'deploy'),
                     edge('deploy', 'rollback', condition='always')], 'an edge has another condition'),
    (RELEASE_NODES, [edge('build', 'sign-off'), edge('deploy', 'sign-off'),
                     edge('deploy', 'rollback')], 'an edge points the other way'),
    (RELEASE_NODES, RELEASE_EDGES[:2], 'an edge is missing'),
    (RELEASE_NODES[:3], RELEASE_EDGES[:2], 'a node is missing'),
    ([node('build', template='build', task_params=dict(variables={'release': '2.0'}))] + RELEASE_NODES[1:],
     RELEASE_EDGES, 'a task variable differs'),
    ([node('build', template='build'), node('sign-off', kind='delay'), node('deploy', template='deploy'),
      node('rollback', template='rollback')], RELEASE_EDGES, 'a node is of another kind'),
])
def test_a_graph_that_differs_is_not_paired(nodes, edges, why):
    assert match_graph(nodes, edges, *stored()) is None, why


def test_a_node_without_kind_is_a_task_node_and_does_not_pair_with_an_approval():
    nodes = [node('a', template='build'), node('b')]
    stored_nodes = [dict(id=1, kind='task', template_id=10), dict(id=2, kind='approval')]
    assert match_graph(nodes, [], *stored(stored_nodes, [])) is None


def test_identical_nodes_are_told_apart_by_their_edges():
    # Two approvals with the same fields; only one of them leads to deploy.
    stored_nodes = [dict(id=1, kind='task', template_id=10), dict(id=2, kind='approval'),
                    dict(id=3, kind='approval'), dict(id=4, kind='task', template_id=11)]
    stored_edges = [dict(source_node_id=1, destination_node_id=2), dict(source_node_id=1, destination_node_id=3),
                    dict(source_node_id=3, destination_node_id=4)]
    nodes = [node('start', template='build'), node('gate', kind='approval'), node('dead-end', kind='approval'),
             node('end', template='deploy')]
    edges = [edge('start', 'gate'), edge('start', 'dead-end'), edge('gate', 'end')]
    assert match_graph(nodes, edges, *stored(stored_nodes, stored_edges)) == {
        'start': 1, 'gate': 3, 'dead-end': 2, 'end': 4}


def test_many_identical_nodes_are_paired_without_trying_every_order():
    # 12 identical approvals in a chain: a search over every order would not finish.
    count = 12
    stored_nodes = [dict(id=i, kind='approval') for i in range(1, count + 1)]
    stored_edges = [dict(source_node_id=i, destination_node_id=i + 1) for i in range(1, count)]
    nodes = [node('n%d' % i, kind='approval') for i in range(count)]
    edges = [edge('n%d' % i, 'n%d' % (i + 1)) for i in range(count - 1)]
    pairing = match_graph(nodes, edges, *stored(stored_nodes, stored_edges))
    assert pairing == dict(('n%d' % i, i + 1) for i in range(count))


def test_the_body_numbers_the_nodes_and_points_the_edges_at_the_numbers():
    nodes, edges = graph_body(RELEASE_NODES[:2], RELEASE_EDGES[:1], [], TEMPLATE_IDS)
    assert [(n['id'], n['kind'], n.get('template_id')) for n in nodes] == [(1, 'task', 10), (2, 'approval', None)]
    assert edges == [dict(source_node_id=1, destination_node_id=2, condition='on_success')]


def test_the_body_sends_variables_and_arguments_as_json_text():
    params = dict(variables={'b': 2, 'a': 1}, arguments=['-v'], task_message='hi')
    want = [node('build', template='build', task_params=params)]
    nodes, dummy = graph_body(want, [], [], TEMPLATE_IDS)
    assert nodes[0]['task_params'] == {'environment': '{"a": 1, "b": 2}', 'arguments': '["-v"]', 'message': 'hi'}


def test_a_node_that_matches_a_stored_one_keeps_its_position_and_the_fields_the_task_left_out():
    have = [dict(raw=n, view=node_view(n, TEMPLATES)) for n in STORED_NODES]
    nodes, dummy = graph_body([node('deploy', template='deploy')], [], have, TEMPLATE_IDS)
    assert nodes[0]['position_x'] == 600
    assert nodes[0]['convergence_mode'] == 'all'
    assert nodes[0]['id'] == 1


def test_new_nodes_are_laid_out_one_column_per_step():
    want = [node('a', template='build'), node('b', template='deploy'), node('c', template='rollback'),
            node('d', template='rollback')]
    edges = [edge('a', 'b'), edge('a', 'c'), edge('b', 'd'), edge('c', 'd')]
    nodes, dummy = graph_body(want, edges, [], TEMPLATE_IDS)
    places = dict((n['id'], (n['position_x'], n['position_y'])) for n in nodes)
    assert places == {1: (0, 0), 2: (300, 0), 3: (300, 150), 4: (600, 0)}


def test_a_position_the_task_sets_is_sent_as_it_is():
    nodes, dummy = graph_body([node('a', template='build', position_x=40, position_y=70)], [], [], TEMPLATE_IDS)
    assert (nodes[0]['position_x'], nodes[0]['position_y']) == (40, 70)


@pytest.mark.parametrize('nodes, edges, message', [
    ([node('a', template='build'), node('a', template='deploy')], [], 'a appears more than once'),
    ([node('a')], [], "Node 'a' is a task node and needs template"),
    ([node('a', kind='approval', template='build')], [], 'template is only for task nodes'),
    ([node('a', kind='delay', delay_seconds=0)], [], 'delay_seconds must be 1 or more'),
    ([node('a', kind='approval', delay_seconds=5)], [], 'delay_seconds is only for delay nodes'),
    ([node('a', template='build')], [edge('a', 'b')], "destination 'b' is not the key of a node"),
    ([node('a', template='build')], [edge('a', 'a')], 'cannot lead from a node to itself'),
    ([node('a', template='build'), node('b', kind='approval')], [edge('a', 'b', input_mode='by_name')],
     'only for an edge that leads to a task node'),
    ([node('a', template='build'), node('b', template='deploy')],
     [edge('a', 'b', input_mode='by_name', input_mappings=[dict(var='v', key='k')])], 'only with input_mode: explicit'),
])
def test_a_graph_that_cannot_be_right_fails_naming_the_node_or_edge(nodes, edges, message):
    with pytest.raises(ValueError) as caught:
        validate_graph(nodes, edges)
    assert message in str(caught.value)
