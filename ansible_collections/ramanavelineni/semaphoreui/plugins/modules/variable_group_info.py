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
    type: str
    required: true
  name:
    description:
      - Only return variable groups with this name.
    type: str
'''

EXAMPLES = r'''
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
    resolve_project,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
    variable_group_view as view,
)


def list_groups(module, client):
    client.warn_if_untested()
    base = '/project/%d' % resolve_project(client, module.params['project'])
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
    argument_spec.update(project=dict(type='str', required=True), name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True, **semaphore_module_kwargs())
    run_module(module, lambda client: list_groups(module, client))


if __name__ == '__main__':
    main()
