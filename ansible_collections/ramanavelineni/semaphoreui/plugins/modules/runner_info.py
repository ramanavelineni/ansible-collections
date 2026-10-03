#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: runner_info
short_description: List Semaphore UI runners
version_added: 0.1.0
description:
  - Lists the global runners, or a project's runners with O(project), optionally only the one with
    a given name. Credentials are never returned.
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
      - Name of the project whose runners to list. Leave it unset for the global runners.
      - Project runners need Semaphore Pro; a Community server lists none.
      - Mutually exclusive with O(project_id).
    type: str
  project_id:
    description:
      - Id of the project, as an alternative to O(project).
      - With it the list of projects is not read, so a project is found on a server with 200 or more
        projects too. Semaphore cuts that list off at 200, and O(project) fails there.
      - Mutually exclusive with O(project).
    type: int
    version_added: 0.3.0
  name:
    description:
      - Only return runners with this name.
    type: str
'''

EXAMPLES = r'''
- name: List the global runners
  ramanavelineni.semaphoreui.runner_info:
  register: result

- name: Runners that have not registered yet
  ansible.builtin.debug:
    msg: "{{ result.runners | rejectattr('registered') | map(attribute='name') }}"
'''

RETURN = r'''
runners:
  description:
    - Matching runners, sorted by name.
    - C(status) is only reported by Semaphore 2.19 and newer; it is empty on 2.18.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      name: lxc-runner-1
      project: null
      max_parallel_tasks: 2
      active: true
      tags: [lxc]
      webhook: ""
      is_default: false
      registered: true
      status: online
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_runners(module, client):
    client.warn_if_untested()
    project_id, project = project_ref(client, module.params)
    base = '/project/%d' % project_id if project_id is not None else ''
    out = []
    for runner in client.list(base + '/runners'):
        if project_id is None and runner.get('project_id') is not None:
            continue
        if module.params['name'] is not None and runner.get('name') != module.params['name']:
            continue
        out.append(dict(
            id=runner.get('id'), name=runner.get('name'), project=project,
            max_parallel_tasks=int(runner.get('max_parallel_tasks') or 0),
            active=bool(runner.get('active', False)), tags=sorted(set(runner.get('tags') or [])),
            webhook=runner.get('webhook') or '', is_default=bool(runner.get('is_default', False)),
            registered=bool(runner.get('registered', False)), status=runner.get('status') or ''))
    return dict(changed=False, runners=sorted(out, key=lambda r: (r['name'] or '', r['id'] or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str'), project_id=dict(type='int'), name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True,
                           **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS]))
    run_module(module, lambda client: list_runners(module, client))


if __name__ == '__main__':
    main()
