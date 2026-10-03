#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: project_info
short_description: List Semaphore UI projects
version_added: 0.1.0
description:
  - Lists the projects the authenticated user can see (all projects for an admin), optionally
    only those with a given name.
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
  name:
    description:
      - Only return projects with this name.
    type: str
notes:
  - Semaphore lists at most 200 projects. When the list is that long the module warns that some
    may be missing.
'''

EXAMPLES = r'''
- name: List every project
  ramanavelineni.semaphoreui.project_info:
    url: https://semaphore.example.com
    api_token: "{{ semaphore_api_token }}"
  register: result

- name: Find the homelab project's id
  ramanavelineni.semaphoreui.project_info:
    url: https://semaphore.example.com
    api_token: "{{ semaphore_api_token }}"
    name: homelab
  register: homelab
'''

RETURN = r'''
projects:
  description: Matching projects, sorted by name, in the form the M(ramanavelineni.semaphoreui.project) module returns.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      name: homelab
      alert: false
      alert_chat: ""
      max_parallel_tasks: 0
      type: ""
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    LIST_CAP,
    project_view,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_projects(module, client):
    client.warn_if_untested()
    projects = client.get('/projects') or []
    if len(projects) >= LIST_CAP:
        module.warn('Semaphore returned %d projects, the most it lists; some may be missing.' % len(projects))
    name = module.params['name']
    if name is not None:
        projects = [p for p in projects if p.get('name') == name]
    projects = [project_view(p) for p in projects]
    return dict(changed=False, projects=sorted(projects, key=lambda p: (p.get('name') or '', p.get('id') or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(name=dict(type='str'))
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs()
    )
    run_module(module, lambda client: list_projects(module, client))


if __name__ == '__main__':
    main()
