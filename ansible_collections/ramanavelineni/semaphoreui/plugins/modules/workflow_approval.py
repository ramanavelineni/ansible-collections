#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: workflow_approval
short_description: Approve or reject an approval node of a Semaphore UI workflow run
version_added: 0.6.0
description:
  - Gives the decision a run of a workflow waits for at an approval node.
  - Without O(node_id) the module takes the one approval of the run that waits. When several
    wait, it fails and names their nodes; pick one with O(node_id).
  - An approval that already has the same decision is left as it is. One with the other decision
    makes the module fail, because a decision cannot be changed.
  - Workflows need Semaphore 2.19 or later, in a build that has them, as the official images do. The
    module checks C(features.workflows) in Semaphore's C(/info) and fails clearly on a server without them.
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
    support: none
options:
  project_id:
    version_added: 0.6.0
  workflow:
    description: Name of the workflow.
    type: str
    required: true
  run_id:
    description: Id of the run.
    type: int
    required: true
  node_id:
    description:
      - Id of the approval node, as in RV(ramanavelineni.semaphoreui.workflow_run#module:run.pending_approvals).
      - Needed when more than one approval of the run waits.
    type: int
  decision:
    description: Whether to approve or reject.
    type: str
    required: true
    choices: [approved, rejected]
seealso:
  - module: ramanavelineni.semaphoreui.workflow_run
    description: Runs a workflow, and waits for it after the decision.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Approve the one approval the run waits for
  ramanavelineni.semaphoreui.workflow_approval:
    project: homelab
    workflow: release
    run_id: 7
    decision: approved

- name: Reject one of several
  ramanavelineni.semaphoreui.workflow_approval:
    project: homelab
    workflow: release
    run_id: 7
    node_id: 32
    decision: rejected
'''

RETURN = r'''
approval:
  description: The approval after the task. In check mode, as it would be.
  returned: always
  type: dict
  contains:
    id:
      description: Approval id.
      type: int
    run_id:
      description: Id of the run.
      type: int
    node_id:
      description: Id of the approval node.
      type: int
    status:
      description: V(pending), V(approved) or V(rejected).
      type: str
    created:
      description: When the run reached the node.
      type: str
    resolved:
      description: When the decision was given. Empty while it waits.
      type: str
    resolved_by_user_id:
      description: Id of the user who gave the decision. Null while it waits.
      type: int
  sample:
    id: 3
    run_id: 7
    node_id: 32
    status: approved
    created: "2026-11-08T16:01:02Z"
    resolved: "2026-11-08T16:05:40Z"
    resolved_by_user_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_REQUIRED,
    project_argument_spec,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.workflow import get_run, require_workflow, workflow_version


def approval_view(approval):
    return dict(
        id=approval.get('id'),
        run_id=approval.get('workflow_run_id'),
        node_id=approval.get('workflow_node_id'),
        status=approval.get('status') or '',
        created=approval.get('created') or '',
        resolved=approval.get('resolved') or '',
        resolved_by_user_id=approval.get('resolved_by_user_id'),
    )


def pick(approvals, node_id, decision, what):
    """The approval to decide on."""
    if node_id is not None:
        found = [a for a in approvals if a.get('workflow_node_id') == node_id]
        if not found:
            raise ValueError('%s has no approval at node %d (approvals at nodes: %s).'
                             % (what, node_id, ', '.join(str(a.get('workflow_node_id')) for a in approvals) or 'none'))
        return found[0]
    pending = [a for a in approvals if a.get('status') == 'pending']
    if len(pending) == 1:
        return pending[0]
    if len(pending) > 1:
        raise ValueError('%s waits for more than one approval, at nodes %s. Pick one with node_id.'
                         % (what, ', '.join(str(a.get('workflow_node_id')) for a in pending)))
    # Nothing waits: a repeat of a decision already given is no change.
    if len(approvals) == 1:
        return approvals[0]
    if not approvals:
        raise ValueError('%s waits for no approval and has had none.' % what)
    same = [a for a in approvals if a.get('status') == decision]
    raise ValueError('%s waits for no approval. It had approvals at nodes %s; pass node_id to check one of them.'
                     % (what, ', '.join(str(a.get('workflow_node_id')) for a in same or approvals)))


def run(module, client):
    client.warn_if_untested()
    workflow_version(client)
    params = module.params
    project_id, project = project_ref(client, params)
    base = '/project/%d' % project_id
    workflow = require_workflow(client, base, params['workflow'], project)
    what = 'Run %d of workflow %r' % (params['run_id'], workflow['name'])
    if get_run(client, base, workflow['id'], params['run_id']) is None:
        raise ValueError('Workflow %r has no run %d.' % (workflow['name'], params['run_id']))
    path = '%s/workflows/%d/runs/%d/approvals' % (base, workflow['id'], params['run_id'])
    approval = pick(client.list(path), params['node_id'], params['decision'], what)
    status = approval.get('status')
    if status == params['decision']:
        return dict(changed=False, approval=approval_view(approval))
    if status != 'pending':
        raise ValueError('%s: the approval at node %s is already %s; a decision cannot be changed.'
                         % (what, approval.get('workflow_node_id'), status))
    if module.check_mode:
        return dict(changed=True, approval=dict(approval_view(approval), status=params['decision']))
    resolved = client.post('%s/%d' % (path, approval['workflow_node_id']), dict(status=params['decision']),
                           expected=(200,))
    return dict(changed=True, approval=approval_view(resolved or dict(approval, status=params['decision'])))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project_argument_spec(),
        workflow=dict(type='str', required=True),
        run_id=dict(type='int', required=True),
        node_id=dict(type='int'),
        decision=dict(type='str', required=True, choices=['approved', 'rejected']),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True,
                           **semaphore_module_kwargs(project=PROJECT_REQUIRED))
    run_module(module, lambda client: run(module, client), placeholder=dict(approval={}))


if __name__ == '__main__':
    main()
