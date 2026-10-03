#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: repository_info
short_description: List the repositories in a Semaphore UI project
version_added: 0.1.0
description:
  - Lists a project's repositories, optionally only the one with a given name.
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
      - Only return repositories with this name.
    type: str
'''

EXAMPLES = r'''
- name: List the homelab project's repositories
  ramanavelineni.semaphoreui.repository_info:
    project: homelab
  register: result
'''

RETURN = r'''
repositories:
  description: Matching repositories, sorted by name, in the form the M(ramanavelineni.semaphoreui.repository) module
    returns, with the name of the key each one uses.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      name: ansible
      git_url: git@github.com:example/ansible.git
      git_branch: main
      ssh_key: github-deploy
      ssh_key_id: 4
      project_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    repository_view,
    resolve_project,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_repositories(module, client):
    client.warn_if_untested()
    project_id = resolve_project(client, module.params['project'])
    base = '/project/%d' % project_id
    key_names = dict((k['id'], k['name']) for k in client.list(base + '/keys'))
    repos = []
    for repo in client.list(base + '/repositories'):
        if module.params['name'] is not None and repo.get('name') != module.params['name']:
            continue
        repos.append(repository_view(repo, key_names))
    return dict(changed=False, repositories=sorted(repos, key=lambda r: (r.get('name') or '', r.get('id') or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        name=dict(type='str'),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs()
    )
    run_module(module, lambda client: list_repositories(module, client))


if __name__ == '__main__':
    main()
