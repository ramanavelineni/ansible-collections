# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Workflows as the workflow modules read and write them.

Written from Semaphore's public API description (api-docs.yml of
semaphoreui/semaphore, 2.19 and 2.20). A server has workflows when /info says
so in features.workflows: the official images of 2.19 and later do, 2.18 and
builds without Semaphore's Pro module do not. 2.20 starts a run with
POST .../runs instead of .../run, and stores more: delay and note nodes,
a survey, survey inputs of a node and input mappings of an edge.

A workflow is a graph. Its nodes have no name, and its edges point at node
ids the server gives out, so a task names each node with a `key` of its own
and the edges refer to those keys. The keys exist only in the task; to
compare, the modules look for a way to pair every declared node with a stored
one so that the nodes and the edges agree (match_graph).
"""

import json

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    MissingReference,
    SemaphoreError,
    find_by_name,
    json_field,
    server_minor,
)
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.template import SURVEY_TO_API, survey_view

NODE_KINDS = ('task', 'approval', 'note', 'delay')
EDGE_CONDITIONS = ('on_success', 'on_failure', 'always')
INPUT_MODES = ('by_name', 'explicit')
CONVERGENCE_MODES = ('all', 'any')

# A run in one of these is over. "approval" waits for a person.
FINAL_RUN_STATUSES = ('success', 'failed', 'stopped')
WAITS_FOR_APPROVAL = 'approval'

# Node fields compared as they are; task_params, survey_inputs and the template
# have their own rules.
NODE_SCALARS = ('kind', 'convergence_mode', 'approval_timeout', 'approval_message', 'delay_seconds', 'note',
                'position_x', 'position_y')
EDGE_SCALARS = ('condition', 'input_mode')
# task_params keys as the task gives them -> as the API stores them.
TASK_PARAM_KEYS = (('variables', 'environment'), ('git_branch', 'git_branch'), ('task_message', 'message'),
                   ('arguments', 'arguments'), ('params', 'params'))
# What only 2.20 and later store.
NEWER = (2, 20)
NEWER_KINDS = ('note', 'delay')
NEWER_NODE_FIELDS = ('delay_seconds', 'note', 'survey_inputs')
NEWER_EDGE_FIELDS = ('input_mode', 'input_mappings')

# Nodes laid out for the UI when the task gives no position: one column per
# step from the first node, one row per node in a column.
COLUMN_WIDTH = 300
ROW_HEIGHT = 150


def workflow_version(client):
    """(major, minor) of a server that has workflows; fails on one that has none.

    A version that doesn't parse is taken as the newest shape.
    """
    info = client.info()
    if not (info.get('features') or {}).get('workflows'):
        raise ValueError(
            'Semaphore at %s (version %s) has no workflows: /info does not list features.workflows as on. '
            'Workflows need Semaphore 2.19 or later, in a build that includes them, as the official images do.'
            % (client.url, info.get('version') or 'unknown'))
    return server_minor(info.get('version') or '') or NEWER


def refuse_newer_fields(version, nodes, edges, survey):
    """Fail on what a server before 2.20 does not store, naming it."""
    if version >= NEWER:
        return
    found = []
    if survey is not None:
        found.append('survey_vars')
    for node in nodes or []:
        if node.get('kind') in NEWER_KINDS:
            found.append('kind %s (node %r)' % (node['kind'], node['key']))
        found.extend('%s (node %r)' % (f, node['key']) for f in NEWER_NODE_FIELDS if node.get(f) is not None)
    for edge in edges or []:
        found.extend('%s (edge %s -> %s)' % (f, edge['source'], edge['destination'])
                     for f in NEWER_EDGE_FIELDS if edge.get(f) is not None)
    if found:
        raise ValueError('Semaphore %d.%d does not store %s; that needs 2.20 or later.'
                         % (version[0], version[1], ', '.join(found)))


def no_workflow_api(client, error):
    """The failure for a request a server with workflows should know, answered with 404 or 405."""
    return ValueError(
        'Semaphore at %s answered %s %s with %s. This server does not have this part of the workflow API.'
        % (client.url, error.method, error.url, error.status))


def find_workflow(client, base, name):
    """The workflow named `name`, read on its own (with its nodes and edges), or None."""
    found = find_by_name(client.list(base + '/workflows'), name, 'workflow')
    if found is None:
        return None
    return client.get('%s/workflows/%d' % (base, found['id'])) or {}


def require_workflow(client, base, name, project):
    found = find_workflow(client, base, name)
    if found is None:
        raise MissingReference('Workflow %r does not exist in project %r.' % (name, project))
    return found


# -- views ---------------------------------------------------------------------


def task_params_view(params):
    """A node's task_params as the modules return them: variables and arguments parsed (see json_field)."""
    params = params or {}
    out = {}
    for option, field in TASK_PARAM_KEYS:
        if field not in params:
            continue
        value = params[field]
        if field == 'environment':
            value = json_field(value, {})
        elif field == 'arguments':
            value = json_field(value, [])
        out[option] = value
    return out


def task_params_to_api(given):
    """task_params as a task gives them, in the API's shape: variables and arguments as JSON in a string."""
    out = {}
    for option, field in TASK_PARAM_KEYS:
        if given.get(option) is None:
            continue
        value = given[option]
        if field in ('environment', 'arguments'):
            value = json.dumps(value, sort_keys=True)
        out[field] = value
    return out


def node_view(node, templates):
    """A stored node with every field filled in; `templates` maps template id -> name."""
    return dict(
        id=node.get('id'),
        kind=node.get('kind') or 'task',
        template=templates.get(node.get('template_id')),
        convergence_mode=node.get('convergence_mode') or '',
        approval_timeout=int(node.get('approval_timeout') or 0),
        approval_message=node.get('approval_message') or '',
        delay_seconds=int(node.get('delay_seconds') or 0),
        note=node.get('note') or '',
        position_x=int(node.get('position_x') or 0),
        position_y=int(node.get('position_y') or 0),
        task_params=task_params_view(node.get('task_params')),
        survey_inputs=sorted((dict(var=s.get('var'), workflow_var=s.get('workflow_var'))
                              for s in node.get('survey_inputs') or []), key=lambda s: (s['var'], s['workflow_var'])),
    )


def edge_view(edge, keys):
    """A stored edge; `keys` maps node id -> the key the node goes by."""
    return dict(
        source=keys.get(edge.get('source_node_id')),
        destination=keys.get(edge.get('destination_node_id')),
        condition=edge.get('condition') or '',
        input_mode=edge.get('input_mode') or '',
        input_mappings=sorted((dict(var=m.get('var'), key=m.get('key')) for m in edge.get('input_mappings') or []),
                              key=lambda m: (m['var'], m['key'])),
    )


def stored_key(node_id):
    """The key a stored node goes by when no task named it."""
    return 'node%s' % node_id


def workflow_view(workflow, project, templates, keys=None):
    """A workflow as the workflow modules return it.

    `keys` maps node id -> key; nodes it leaves out go by stored_key().
    Nodes are in the order the server gives them, edges sorted.
    """
    keys = dict(keys or {})
    nodes = []
    for node in workflow.get('nodes') or []:
        keys.setdefault(node.get('id'), stored_key(node.get('id')))
        nodes.append(dict(node_view(node, templates), key=keys[node.get('id')]))
    edges = sorted((edge_view(e, keys) for e in workflow.get('edges') or []),
                   key=lambda e: (e['source'] or '', e['destination'] or '', e['condition']))
    return dict(
        id=workflow.get('id'),
        name=workflow.get('name'),
        project=project,
        project_id=workflow.get('project_id'),
        description=workflow.get('description') or '',
        revision=workflow.get('revision'),
        survey_vars=[survey_view(v) for v in workflow.get('survey_vars') or []],
        nodes=nodes,
        edges=edges,
    )


# -- the graph a task declares ---------------------------------------------------


def desired_node(node):
    """A declared node in node_view()'s shape; None marks a field the task leaves alone."""
    out = dict((k, node.get(k)) for k in NODE_SCALARS)
    out['key'] = node['key']
    out['template'] = node.get('template')
    out['task_params'] = None if node.get('task_params') is None else dict(
        (k, v) for k, v in node['task_params'].items() if v is not None)
    out['survey_inputs'] = None if node.get('survey_inputs') is None else sorted(
        (dict(var=s['var'], workflow_var=s['workflow_var']) for s in node['survey_inputs']),
        key=lambda s: (s['var'], s['workflow_var']))
    return out


def desired_edge(edge):
    out = dict((k, edge.get(k)) for k in EDGE_SCALARS)
    out['source'] = edge['source']
    out['destination'] = edge['destination']
    out['input_mappings'] = None if edge.get('input_mappings') is None else sorted(
        (dict(var=m['var'], key=m['key']) for m in edge['input_mappings']), key=lambda m: (m['var'], m['key']))
    return out


def validate_graph(nodes, edges):
    """Fail on a declared graph that cannot be right, naming the bad node or edge."""
    keys = [n['key'] for n in nodes]
    twice = sorted(set(k for k in keys if keys.count(k) > 1))
    if twice:
        raise ValueError('Node keys must be unique within a workflow; %s appears more than once.' % ', '.join(twice))
    kinds = dict((n['key'], n.get('kind') or 'task') for n in nodes)
    for node in nodes:
        kind = kinds[node['key']]
        if kind == 'task' and not node.get('template'):
            raise ValueError('Node %r is a task node and needs template.' % node['key'])
        if kind != 'task':
            for option in ('template', 'task_params', 'survey_inputs'):
                if node.get(option) is not None:
                    raise ValueError('Node %r is of kind %s; %s is only for task nodes.' % (node['key'], kind, option))
        if kind == 'delay' and node.get('delay_seconds') is not None and node['delay_seconds'] < 1:
            raise ValueError('Node %r: delay_seconds must be 1 or more.' % node['key'])
        if kind != 'delay' and node.get('delay_seconds') is not None:
            raise ValueError('Node %r is of kind %s; delay_seconds is only for delay nodes.' % (node['key'], kind))
    for edge in edges:
        where = 'Edge %s -> %s' % (edge['source'], edge['destination'])
        for end in ('source', 'destination'):
            if edge[end] not in kinds:
                raise ValueError('%s: %s %r is not the key of a node of this workflow.' % (where, end, edge[end]))
        if edge['source'] == edge['destination']:
            raise ValueError('%s: an edge cannot lead from a node to itself.' % where)
        if (edge.get('input_mode') or edge.get('input_mappings') is not None) and kinds[edge['destination']] != 'task':
            raise ValueError('%s: input_mode and input_mappings are only for an edge that leads to a task node.' % where)
        if edge.get('input_mappings') and edge.get('input_mode') != 'explicit':
            raise ValueError('%s: input_mappings are used only with input_mode: explicit.' % where)


def node_matches(want, have):
    """Whether a stored node (node_view) has every field the declared node (desired_node) sets."""
    for field in NODE_SCALARS + ('template', 'survey_inputs'):
        if want.get(field) is not None and want[field] != have[field]:
            return False
    if want.get('kind') is None and have['kind'] != 'task':
        return False
    if want.get('task_params') is not None:
        if any(have['task_params'].get(k) != v for k, v in want['task_params'].items()):
            return False
    return True


def edge_matches(want, have):
    for field in EDGE_SCALARS + ('input_mappings',):
        if want.get(field) is not None and want[field] != have[field]:
            return False
    return True


def match_graph(want_nodes, want_edges, have_nodes, have_edges):
    """{key: stored node id} pairing every declared node with a stored one so that nodes and edges agree, or None.

    have_nodes are node_view()s; have_edges are edge_view()s keyed by stored_key().
    Searches by backtracking, the node with the fewest candidates first, and
    drops a pairing as soon as an edge between two paired nodes has no
    counterpart. Workflows are small, so this stays fast in practice.
    """
    if len(want_nodes) != len(have_nodes) or len(want_edges) != len(have_edges):
        return None
    candidates = dict((w['key'], [h['id'] for h in have_nodes if node_matches(w, h)]) for w in want_nodes)
    if any(not c for c in candidates.values()):
        return None
    order = sorted(candidates, key=lambda k: len(candidates[k]))

    def edges_fit(pairing, final):
        """Every declared edge between paired nodes has its own stored edge; with final, all edges are used."""
        unused = list(have_edges)
        for edge in want_edges:
            if edge['source'] not in pairing or edge['destination'] not in pairing:
                continue
            src, dst = stored_key(pairing[edge['source']]), stored_key(pairing[edge['destination']])
            for i, have in enumerate(unused):
                if have['source'] == src and have['destination'] == dst and edge_matches(edge, have):
                    del unused[i]
                    break
            else:
                return False
        return not final or not unused

    def search(i, pairing, used):
        if i == len(order):
            return dict(pairing) if edges_fit(pairing, True) else None
        key = order[i]
        for node_id in candidates[key]:
            if node_id in used:
                continue
            pairing[key] = node_id
            used.add(node_id)
            if edges_fit(pairing, False):
                found = search(i + 1, pairing, used)
                if found is not None:
                    return found
            del pairing[key]
            used.discard(node_id)
        return None

    return search(0, {}, set())


def layout(nodes, edges, positioned):
    """{key: (x, y)} for the nodes not in `positioned`: a column per step from the first nodes."""
    depth = dict((n['key'], 0) for n in nodes)
    # Longest path from a node without incoming edges; a cycle is cut after len(nodes) rounds.
    for dummy in range(len(nodes)):
        moved = False
        for edge in edges:
            if depth[edge['destination']] < depth[edge['source']] + 1 <= len(nodes):
                depth[edge['destination']] = depth[edge['source']] + 1
                moved = True
        if not moved:
            break
    rows = {}
    out = {}
    for node in nodes:
        column = depth[node['key']]
        row = rows.get(column, 0)
        rows[column] = row + 1
        if node['key'] not in positioned:
            out[node['key']] = (column * COLUMN_WIDTH, row * ROW_HEIGHT)
    return out


def graph_body(want_nodes, want_edges, have_nodes, template_ids):
    """(nodes, edges) as the API takes them, for a declared graph.

    A declared node starts from a stored node it matches, when one is left,
    so the fields the task leaves out (its position among them) keep their
    stored value. Every node gets a number of its own as id, and the edges
    refer to those numbers.
    """
    unused = list(have_nodes)
    positioned = set()
    bases = {}
    for want in want_nodes:
        for i, have in enumerate(unused):
            if node_matches(want, have['view']):
                bases[want['key']] = have['raw']
                del unused[i]
                positioned.add(want['key'])
                break
        if want.get('position_x') is not None or want.get('position_y') is not None:
            positioned.add(want['key'])
    places = layout(want_nodes, want_edges, positioned)
    numbers = dict((w['key'], i + 1) for i, w in enumerate(want_nodes))
    nodes = []
    for want in want_nodes:
        node = dict(bases.get(want['key']) or {})
        for field in ('workflow_template_id',):
            node.pop(field, None)
        node['id'] = numbers[want['key']]
        for field in NODE_SCALARS:
            if want.get(field) is not None:
                node[field] = want[field]
        node.setdefault('kind', 'task')
        if want['key'] in places:
            node['position_x'], node['position_y'] = places[want['key']]
        if want.get('template') is not None:
            node['template_id'] = template_ids[want['template']]
        if want.get('task_params') is not None:
            stored = dict(node.get('task_params') or {})
            stored.update(task_params_to_api(want['task_params']))
            node['task_params'] = stored
        if want.get('survey_inputs') is not None:
            node['survey_inputs'] = want['survey_inputs']
        nodes.append(node)
    edges = []
    for want in want_edges:
        edge = dict(source_node_id=numbers[want['source']], destination_node_id=numbers[want['destination']])
        for field in EDGE_SCALARS + ('input_mappings',):
            if want.get(field) is not None:
                edge[field] = want[field]
        edges.append(edge)
    return nodes, edges


def renumbered(workflow):
    """(nodes, edges) of a stored workflow as an update sends them back: numbered like graph_body() does."""
    numbers = dict((n.get('id'), i + 1) for i, n in enumerate(workflow.get('nodes') or []))
    nodes = []
    for node in workflow.get('nodes') or []:
        node = dict((k, v) for k, v in node.items() if k != 'workflow_template_id')
        node['id'] = numbers[node.get('id')]
        nodes.append(node)
    edges = [dict(dict((k, v) for k, v in edge.items() if k not in ('id', 'workflow_template_id')),
                  source_node_id=numbers.get(edge.get('source_node_id')),
                  destination_node_id=numbers.get(edge.get('destination_node_id')))
             for edge in workflow.get('edges') or []]
    return nodes, edges


def survey_to_api(var):
    out = dict(name=var['name'], title=var['title'], type=SURVEY_TO_API.get(var['type'], var['type']),
               required=var['required'], description=var['description'], default_value=var['default_value'])
    if var.get('values'):
        out['values'] = [dict(name=v['name'], value=v['value']) for v in var['values']]
    return out


# -- runs ----------------------------------------------------------------------


def get_run(client, base, workflow_id, run_id):
    """The run details (run, nodes, edges), or None when the workflow has no such run."""
    try:
        return client.get('%s/workflows/%d/runs/%d' % (base, workflow_id, run_id))
    except SemaphoreError as e:
        if e.status in (400, 404):
            return None
        raise


def run_view(details, project, workflow, templates):
    """A run as workflow_run returns it, from the run details."""
    run = details.get('run') or details
    status = run.get('status') or ''
    nodes = []
    for entry in details.get('nodes') or []:
        node = entry.get('node') or {}
        task = entry.get('task') or {}
        approval = entry.get('approval') or {}
        nodes.append(dict(
            node_id=node.get('id'),
            kind=node.get('kind') or 'task',
            template=templates.get(node.get('template_id')),
            task_id=task.get('id'),
            task_status=task.get('status') or '',
            approval_status=approval.get('status') or '',
        ))
    return dict(
        id=run.get('id'),
        project=project,
        workflow=workflow,
        workflow_id=run.get('workflow_template_id'),
        revision_id=run.get('revision_id'),
        status=status,
        finished=status in FINAL_RUN_STATUSES,
        variables=dict(run.get('environment') or {}),
        start=run.get('start') or '',
        end=run.get('end') or '',
        root_task_id=run.get('root_task_id'),
        nodes=nodes,
        pending_approvals=[n['node_id'] for n in nodes if n['approval_status'] == 'pending'],
    )
