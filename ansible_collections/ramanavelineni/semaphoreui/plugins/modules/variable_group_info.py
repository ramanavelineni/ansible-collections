#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: variable_group_info
short_description: List the variable groups in a Semaphore UI project
version_added: 0.1.0
description:
  - Lists a project's variable groups (environments in Semaphore's API), optionally only the one
    with a given name, with their extra variables, environment variables and the names and types
    of their secrets. Secret values are never returned by Semaphore.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: none
options:
  project:
    description:
      - Name of the project.
      - Mutually exclusive with O(project_id); one of the two is required.
    type: str
  project_id:
    description:
      - Id of the project, as an alternative to O(project).
      - With it the list of projects is not read, so a project is found on a server with 200 or more
        projects too. Semaphore cuts that list off at 200, and O(project) fails there.
      - Mutually exclusive with O(project). One of the two is required.
    type: int
    version_added: 0.3.0
  name:
    description:
      - Only return variable groups with this name.
    type: str
seealso:
  - module: ramanavelineni.semaphoreui.variable_group
    description: Creates, changes and deletes variable groups.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: List the homelab project's variable groups
  ramanavelineni.semaphoreui.variable_group_info:
    project: homelab
  register: result
'''

RETURN = r'''
variable_groups:
  description: Matching variable groups, sorted by name.
  returned: always
  type: list
  elements: dict
  contains:
    id:
      description: Variable group id.
      type: int
    name:
      description: Name of the variable group.
      type: str
    project_id:
      description: Id of the project.
      type: int
    json:
      description: Extra variables passed to Ansible.
      type: dict
    env:
      description: Environment variables for the task's process.
      type: dict
    secrets:
      description: The group's secrets, sorted by name. Values are never returned.
      type: list
      elements: dict
      contains:
        name:
          description: Name of the variable.
          type: str
        type:
          description: V(env) for an environment variable, V(var) for an extra variable.
          type: str
  sample:
    - id: 1
      name: harbor
      project_id: 1
      json:
        harbor_url: https://harbor.example.com
      env:
        TZ: UTC
      secrets:
        - name: HARBOR_TOKEN
          type: env
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
    variable_group_view as view,
)


def list_groups(module, client):
    client.warn_if_untested()
    base = '/project/%d' % project_ref(client, module.params)[0]
    out = []
    for group in client.list(base + '/environment'):
        if module.params['name'] is not None and group.get('name') != module.params['name']:
            continue
        # The list leaves secrets out; the single read has their names and types.
        full = client.get('%s/environment/%d' % (base, group['id'])) or group
        out.append(view(full, full.get('secrets') or []))
    return dict(changed=False, variable_groups=sorted(out, key=lambda g: (g['name'] or '', g['id'] or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str'), project_id=dict(type='int'), name=dict(type='str'))
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: list_groups(module, client))


if __name__ == '__main__':
    main()
