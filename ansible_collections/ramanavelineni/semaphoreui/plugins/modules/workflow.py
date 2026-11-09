#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: workflow
short_description: Manage a Semaphore UI workflow
version_added: 0.6.0
description:
  - Creates, updates or deletes a workflow of a project, found by name. A workflow runs templates
    one after another as a graph. Its nodes are the steps, and its edges say which step follows which.
  - Workflows need Semaphore 2.19 or later, in a build that has them, as the official images do. The
    module checks C(features.workflows) in Semaphore's C(/info) and fails clearly on a server without them.
  - Delay and note nodes, O(survey_vars), O(nodes[].delay_seconds), O(nodes[].note),
    O(nodes[].survey_inputs), O(edges[].input_mode) and O(edges[].input_mappings) need Semaphore 2.20.
    On 2.19 the module fails when one of them is set.
  - Nodes have no name in Semaphore, and edges point at ids the server gives out. In a task every
    node has a O(nodes[].key) of its own, and the edges refer to those keys. The keys are not stored;
    the module pairs each declared node with a stored one whose fields agree, and the edges have to
    agree between the paired nodes. When no such pairing exists, the graph is saved anew.
  - Fields of a node the task leaves out keep their stored value, as far as a stored node with the
    fields the task does set is there.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
  - ramanavelineni.semaphoreui.project
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
options:
  project_id:
    version_added: 0.6.0
  name:
    description: Name of the workflow.
    type: str
    required: true
  state:
    description: Whether the workflow should exist.
    type: str
    choices: [present, absent]
    default: present
  description:
    description: Description of the workflow.
    type: str
  survey_vars:
    description:
      - Variables asked for when a run is started, replacing the current list as a whole. Nodes get
        their values through O(nodes[].survey_inputs).
      - Semaphore refuses secret variables in a workflow's survey.
    type: list
    elements: dict
    suboptions:
      name:
        description: Variable name.
        type: str
        required: true
      title:
        description: Label shown to the user.
        type: str
        required: true
      type:
        description: V(string) (the default), V(int), V(enum), V(select) (several of O(survey_vars[].values)) or V(text).
        type: str
        choices: [string, int, enum, select, text]
        default: string
      required:
        description: Whether a value must be given.
        type: bool
        default: false
      description:
        description: Help text.
        type: str
        default: ''
      default_value:
        description: Value filled in by default. A list of strings for V(select).
        type: raw
        default: ''
      values:
        description: Choices for V(enum) and V(select).
        type: list
        elements: dict
        suboptions:
          name:
            description: Label of the choice.
            type: str
            required: true
          value:
            description: Value of the choice.
            type: str
            required: true
  nodes:
    description:
      - The steps of the workflow, replacing the current graph as a whole when it differs.
      - Left out, the graph is not managed. Required to create a workflow.
      - Semaphore refuses a workflow without nodes, so the list cannot be empty.
    type: list
    elements: dict
    suboptions:
      key:
        description:
          - Name of the node within this task, used by O(edges). Not stored in Semaphore.
          - Unique within the workflow.
        type: str
        required: true
      kind:
        description:
          - V(task) runs O(nodes[].template). V(approval) waits until a person approves or rejects.
            V(delay) waits O(nodes[].delay_seconds). V(note) is a comment on the canvas.
          - Left out, V(task).
        type: str
        choices: [task, approval, note, delay]
      template:
        description: Name of the template a task node runs. Required for a task node.
        type: str
      convergence_mode:
        description: For a node that several edges lead to, whether it starts after V(all) of them or after V(any).
        type: str
        choices: [all, any]
      approval_timeout:
        description: Seconds an approval node waits for a decision.
        type: int
      approval_message:
        description: Text shown with an approval node.
        type: str
      delay_seconds:
        description: Seconds a delay node waits, 1 or more.
        type: int
      note:
        description: Text of the node.
        type: str
      position_x:
        description:
          - Position of the node on the canvas.
          - Left out, a matching stored node keeps its position, and a new node is placed in a column
            per step from the first nodes.
        type: int
      position_y:
        description: Position of the node on the canvas. See O(nodes[].position_x).
        type: int
      task_params:
        description: What a task node sets for the task it starts, as the task dialog in Semaphore offers it.
        type: dict
        suboptions:
          variables:
            description: Variables of the task.
            type: dict
          git_branch:
            description: Branch to check out.
            type: str
          task_message:
            description: A note shown with the task (the API's C(message)).
            type: str
          arguments:
            description: Command line arguments.
            type: list
            elements: str
          params:
            description:
              - The app's parameters, as in O(ramanavelineni.semaphoreui.task#module:task_params).
            type: dict
      survey_inputs:
        description:
          - Survey variables of the node's template filled from the workflow's survey variables.
        type: list
        elements: dict
        suboptions:
          var:
            description: Survey variable of the node's template.
            type: str
            required: true
          workflow_var:
            description: Survey variable of the workflow (O(survey_vars)) whose value it gets.
            type: str
            required: true
  edges:
    description:
      - Which node follows which. Needs O(nodes).
    type: list
    elements: dict
    suboptions:
      source:
        description: Key of the node the edge leads from.
        type: str
        required: true
      destination:
        description: Key of the node the edge leads to.
        type: str
        required: true
      condition:
        description: Whether the edge is taken V(on_success) of the source node, V(on_failure), or V(always).
        type: str
        choices: [on_success, on_failure, always]
      input_mode:
        description:
          - How outputs of the source node reach the survey variables of the destination, a task node.
          - V(by_name) passes every output whose name is a survey variable; V(explicit) only the
            pairs in O(edges[].input_mappings).
        type: str
        choices: [by_name, explicit]
      input_mappings:
        description: The pairs passed with O(edges[].input_mode=explicit). An empty list passes nothing.
        type: list
        elements: dict
        suboptions:
          var:
            description: Survey variable of the destination's template.
            type: str
            required: true
          key:
            description: Name of an output of the source node.
            type: str
            required: true
notes:
  - Semaphore keeps a revision of a workflow each time its graph is saved. Runs keep the revision
    they started with.
  - Who may do what with a single workflow (its permissions) is not managed and kept as it is.
seealso:
  - module: ramanavelineni.semaphoreui.workflow_info
    description: Reads workflows without changing anything.
  - module: ramanavelineni.semaphoreui.workflow_run
    description: Runs a workflow.
  - module: ramanavelineni.semaphoreui.template
    description: Manages the templates a workflow runs.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Build, approve, then deploy; roll back when the deploy fails
  ramanavelineni.semaphoreui.workflow:
    project: webshop
    name: release
    description: Build and deploy with a sign-off
    survey_vars:
      - name: release
        title: Release to deploy
        required: true
    nodes:
      - key: build
        template: build
        survey_inputs:
          - var: version
            workflow_var: release
      - key: sign-off
        kind: approval
        approval_message: Deploy this build?
        approval_timeout: 3600
      - key: deploy
        template: deploy
      - key: rollback
        template: rollback
    edges:
      - source: build
        destination: sign-off
        condition: on_success
      - source: sign-off
        destination: deploy
        condition: on_success
      - source: deploy
        destination: rollback
        condition: on_failure

- name: Delete a workflow
  ramanavelineni.semaphoreui.workflow:
    project: webshop
    name: release
    state: absent
'''

RETURN = r'''
workflow:
  description:
    - The workflow as Semaphore stores it after the task. Empty after a delete.
    - In check mode, the workflow as it would be. Ids Semaphore would give out are null.
  returned: always
  type: dict
  contains:
    id:
      description: Workflow id.
      type: int
    name:
      description: Name of the workflow.
      type: str
    project:
      description: Name of the project.
      type: str
    project_id:
      description: Id of the project.
      type: int
    description:
      description: Description of the workflow.
      type: str
    revision:
      description: Number of the stored revision of the graph.
      type: int
    survey_vars:
      description: The survey asked when a run is started, in the shape of O(survey_vars).
      type: list
      elements: dict
    nodes:
      description:
        - The nodes, in the order Semaphore gives them, each with every field of O(nodes) and its C(id).
        - C(key) is the task's key of the node. A node the task did not declare is C(node<id>).
      type: list
      elements: dict
    edges:
      description:
        - The edges, with every field of O(edges). C(source) and C(destination) are node keys.
      type: list
      elements: dict
  sample:
    id: 4
    name: release
    project: webshop
    project_id: 1
    description: Build and deploy with a sign-off
    revision: 2
    survey_vars: []
    nodes:
      - key: build
        id: 31
        kind: task
        template: build
        convergence_mode: all
        approval_timeout: 0
        approval_message: ""
        delay_seconds: 0
        note: ""
        position_x: 0
        position_y: 0
        task_params: {}
        survey_inputs: []
    edges: []
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    MissingReference,
    PROJECT_REQUIRED,
    SemaphoreError,
    project_argument_spec,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.template import survey_view
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.task import template_names
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.workflow import (
    CONVERGENCE_MODES,
    EDGE_CONDITIONS,
    NEWER,
    INPUT_MODES,
    NODE_KINDS,
    desired_edge,
    desired_node,
    edge_view,
    find_workflow,
    graph_body,
    match_graph,
    no_workflow_api,
    node_view,
    refuse_newer_fields,
    renumbered,
    stored_key,
    survey_to_api,
    validate_graph,
    workflow_version,
    workflow_view,
)

# What the API returns and sets itself; not sent back with an update.
READ_ONLY = ('permissions', 'revision_id', 'revision')


def desired_survey(params):
    if params['survey_vars'] is None:
        return None
    for var in params['survey_vars']:
        if var['type'] in ('enum', 'select') and not var['values']:
            raise ValueError('Survey variable %r of type %s needs values.' % (var['name'], var['type']))
        if isinstance(var['default_value'], list) and var['type'] != 'select':
            raise ValueError('Survey variable %r: only a select variable takes a list as default_value.' % var['name'])
    return [survey_view(survey_to_api(v)) for v in params['survey_vars']]


def check_templates(nodes, templates, project):
    for node in nodes:
        if node.get('template') is not None and node['template'] not in templates:
            raise MissingReference('Template %r of node %r does not exist in project %r.'
                                   % (node['template'], node['key'], project))


def pairing(workflow, want_nodes, want_edges, names):
    """{stored node id: key} for the declared graph, or None when the stored graph differs."""
    have_nodes = [node_view(n, names) for n in workflow.get('nodes') or []]
    have_edges = [edge_view(e, dict((n['id'], stored_key(n['id'])) for n in have_nodes))
                  for e in workflow.get('edges') or []]
    found = match_graph(want_nodes, want_edges, have_nodes, have_edges)
    return None if found is None else dict((node_id, key) for key, node_id in found.items())


def planned_view(body, project, names, want_nodes):
    """The view of a workflow about to be written (check mode): node ids are the request's numbers, shown as null."""
    keys = dict((i + 1, w['key']) for i, w in enumerate(want_nodes))
    view = workflow_view(body, project, names, keys)
    for node in view['nodes']:
        node['id'] = None
    return view


def ensure(module, client):
    client.warn_if_untested()
    params = module.params
    absent = params['state'] == 'absent'
    if params['edges'] is not None and params['nodes'] is None:
        raise ValueError('edges needs nodes: the edges refer to the keys of the nodes.')
    if params['nodes'] == [] and not absent:
        raise ValueError('nodes cannot be empty: Semaphore refuses a workflow without nodes.')
    version = workflow_version(client)
    project_id, project = project_ref(client, params, missing_ok=absent)
    if project_id is None:
        return dict(changed=False, workflow={}, diff=dict(before={}, after={}))
    base = '/project/%d' % project_id
    templates = client.list(base + '/templates')
    names = template_names(templates)
    current = find_workflow(client, base, params['name'])

    if absent:
        if current is None:
            return dict(changed=False, workflow={}, diff=dict(before={}, after={}))
        before = workflow_view(current, project, names)
        if not module.check_mode:
            client.delete('%s/workflows/%d' % (base, current['id']))
        return dict(changed=True, workflow={}, diff=dict(before=before, after={}))

    want_nodes = want_edges = None
    if params['nodes'] is not None:
        want_nodes = [desired_node(n) for n in params['nodes']]
        want_edges = [desired_edge(e) for e in params['edges'] or []]
        validate_graph(want_nodes, want_edges)
    refuse_newer_fields(version, want_nodes, want_edges, params['survey_vars'])
    if want_nodes is not None:
        check_templates(want_nodes, set(names.values()), project)
    template_ids = dict((tpl.get('name'), tpl.get('id')) for tpl in templates)
    survey = desired_survey(params)

    if current is None:
        if want_nodes is None:
            raise ValueError('Workflow %r does not exist; nodes are needed to create it.' % params['name'])
        nodes, edges = graph_body(want_nodes, want_edges, [], template_ids)
        body = dict(project_id=project_id, name=params['name'], description=params['description'] or '',
                    nodes=nodes, edges=edges)
        if version >= NEWER:
            body['survey_vars'] = [survey_to_api(v) for v in params['survey_vars'] or []]
        if module.check_mode:
            return dict(changed=True, workflow=planned_view(body, project, names, want_nodes or []),
                        diff=dict(before={}, after=planned_view(body, project, names, want_nodes or [])))
        try:
            created = client.post(base + '/workflows', body)
        except SemaphoreError as e:
            if e.status == 404:
                raise no_workflow_api(client, e)
            raise
        stored = client.get('%s/workflows/%d' % (base, created['id'])) or created
        after = workflow_view(stored, project, names, pairing(stored, want_nodes or [], want_edges or [], names))
        return dict(changed=True, workflow=after, diff=dict(before={}, after=after))

    keys = None if want_nodes is None else pairing(current, want_nodes, want_edges, names)
    before = workflow_view(current, project, names, keys)
    changed = []
    if params['description'] is not None and params['description'] != before['description']:
        changed.append('description')
    if survey is not None and survey != before['survey_vars']:
        changed.append('survey_vars')
    if want_nodes is not None and keys is None:
        changed.append('graph')
    if not changed:
        return dict(changed=False, workflow=before, diff=dict(before=before, after=before))

    body = dict((k, v) for k, v in current.items() if k not in READ_ONLY)
    if 'description' in changed:
        body['description'] = params['description']
    if 'survey_vars' in changed:
        body['survey_vars'] = [survey_to_api(v) for v in params['survey_vars']]
    if 'graph' in changed:
        have = [dict(raw=n, view=node_view(n, names)) for n in current.get('nodes') or []]
        body['nodes'], body['edges'] = graph_body(want_nodes, want_edges, have, template_ids)
    else:
        body['nodes'], body['edges'] = renumbered(current)
    if module.check_mode:
        after = planned_view(body, project, names, want_nodes) if 'graph' in changed else \
            workflow_view(dict(current, description=body.get('description'), survey_vars=body.get('survey_vars')),
                          project, names, keys)
        return dict(changed=True, workflow=after, diff=dict(before=before, after=after))
    client.put('%s/workflows/%d' % (base, current['id']), body)
    stored = client.get('%s/workflows/%d' % (base, current['id'])) or body
    after = workflow_view(stored, project, names,
                          keys if want_nodes is None else pairing(stored, want_nodes, want_edges, names))
    return dict(changed=True, workflow=after, diff=dict(before=before, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project_argument_spec(),
        name=dict(type='str', required=True),
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        description=dict(type='str'),
        survey_vars=dict(type='list', elements='dict', options=dict(
            name=dict(type='str', required=True),
            title=dict(type='str', required=True),
            type=dict(type='str', default='string', choices=['string', 'int', 'enum', 'select', 'text']),
            required=dict(type='bool', default=False),
            description=dict(type='str', default=''),
            default_value=dict(type='raw', default=''),
            values=dict(type='list', elements='dict', options=dict(
                name=dict(type='str', required=True),
                value=dict(type='str', required=True),
            )),
        )),
        nodes=dict(type='list', elements='dict', options=dict(
            key=dict(type='str', required=True, no_log=False),
            kind=dict(type='str', choices=list(NODE_KINDS)),
            template=dict(type='str'),
            convergence_mode=dict(type='str', choices=list(CONVERGENCE_MODES)),
            approval_timeout=dict(type='int'),
            approval_message=dict(type='str'),
            delay_seconds=dict(type='int'),
            note=dict(type='str'),
            position_x=dict(type='int'),
            position_y=dict(type='int'),
            task_params=dict(type='dict', options=dict(
                variables=dict(type='dict'),
                git_branch=dict(type='str'),
                task_message=dict(type='str'),
                arguments=dict(type='list', elements='str'),
                params=dict(type='dict'),
            )),
            survey_inputs=dict(type='list', elements='dict', options=dict(
                var=dict(type='str', required=True),
                workflow_var=dict(type='str', required=True),
            )),
        )),
        edges=dict(type='list', elements='dict', options=dict(
            source=dict(type='str', required=True),
            destination=dict(type='str', required=True),
            condition=dict(type='str', choices=list(EDGE_CONDITIONS)),
            input_mode=dict(type='str', choices=list(INPUT_MODES)),
            input_mappings=dict(type='list', elements='dict', options=dict(
                var=dict(type='str', required=True),
                key=dict(type='str', required=True, no_log=False),
            )),
        )),
    )
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(project=PROJECT_REQUIRED)
    )
    run_module(module, lambda client: ensure(module, client), placeholder=dict(workflow={}))


if __name__ == '__main__':
    main()
