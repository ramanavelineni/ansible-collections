#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: workflow_info
short_description: Read Semaphore UI workflows
version_added: 0.6.0
description:
  - Returns the workflows of a project, or the one with a given name, each with its nodes and edges.
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
  name:
    description: Return only the workflow with this name.
    type: str
seealso:
  - module: ramanavelineni.semaphoreui.workflow
    description: Manages workflows.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Read every workflow of a project
  ramanavelineni.semaphoreui.workflow_info:
    project: homelab
  register: found

- name: Read one workflow
  ramanavelineni.semaphoreui.workflow_info:
    project: homelab
    name: release
  register: release
'''

RETURN = r'''
workflows:
  description:
    - The workflows, each as M(ramanavelineni.semaphoreui.workflow) returns it.
    - Node keys are C(node<id>), since Semaphore stores no keys.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 4
      name: release
      project: homelab
      project_id: 1
      description: ""
      revision: 2
      survey_vars: []
      nodes:
        - key: node31
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
    PROJECT_REQUIRED,
    project_argument_spec,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.task import template_names
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.workflow import workflow_version, workflow_view


def run(module, client):
    client.warn_if_untested()
    workflow_version(client)
    params = module.params
    project_id, project = project_ref(client, params)
    base = '/project/%d' % project_id
    listed = client.list(base + '/workflows')
    if params['name'] is not None:
        listed = [w for w in listed if w.get('name') == params['name']]
    names = template_names(client.list(base + '/templates')) if listed else {}
    workflows = [client.get('%s/workflows/%d' % (base, w['id'])) or w for w in listed]
    return dict(changed=False, workflows=[workflow_view(w, project, names) for w in workflows])


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project_argument_spec(), name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True,
                           **semaphore_module_kwargs(project=PROJECT_REQUIRED))
    run_module(module, lambda client: run(module, client))


if __name__ == '__main__':
    main()
