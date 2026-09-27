#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: project_info
short_description: List Harbor projects
version_added: 0.1.0
description:
  - Lists the projects the user can see, optionally only the one with a given name, with their
    visibility, metadata, proxy-cache registry and storage quota.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.harbor.auth
  - ramanavelineni.harbor.attributes
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
'''

EXAMPLES = r'''
- name: List every project
  ramanavelineni.harbor.project_info:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
  register: result
'''

RETURN = r'''
projects:
  description: Matching projects, sorted by name, in the same shape as the project module returns.
  returned: always
  type: list
  elements: dict
  sample:
    - project_id: 1
      name: library
      public: true
      metadata: {}
      proxy_registry: null
      registry_id: null
      quota_gb: -1
      repo_count: 0
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    project_view,
    run_module,
)


def list_projects(module, client):
    client.warn_if_untested()
    projects = [p for p in client.list('/projects')
                if module.params['name'] is None or p.get('name') == module.params['name']]
    registries = dict((r['id'], r['name']) for r in client.list('/registries')) if projects else {}
    quotas = dict((q.get('ref', {}).get('id'), q) for q in client.list('/quotas', params=dict(reference='project')))
    out = [project_view(p, quotas.get(p.get('project_id')), registries) for p in projects]
    return dict(changed=False, projects=sorted(out, key=lambda p: (p['name'] or '', p['project_id'] or 0)))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: list_projects(module, client))


if __name__ == '__main__':
    main()
