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
  - Registries and quotas are system-level in Harbor. For a user who is not an administrator, every
    project's quota and proxy-cache registry name are returned as V(null).
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
seealso:
  - module: ramanavelineni.harbor.project
    description: Manage projects.
'''

EXAMPLES = r'''
# The connection options (url, username, password) can be set once instead of on every task, with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

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
  contains:
    project_id:
      description: Harbor's id of the project.
      type: int
    name:
      description: Name of the project.
      type: str
    public:
      description: Whether the project can be pulled from without logging in.
      type: bool
    metadata:
      description:
        - The project's other metadata as Harbor stores it, with every value a string.
        - C(public) is not repeated here.
      type: dict
    registry_id:
      description: Id of the registry a proxy-cache project is bound to, V(null) for any other project.
      type: int
    proxy_registry:
      description:
        - Name of the registry a proxy-cache project is bound to.
        - Also V(null) when the login user is not an administrator and may not read the registries.
      type: str
    quota_gb:
      description:
        - Storage quota in GiB, V(-1) for unlimited.
        - V(null) when the login user is not an administrator and may not read the quotas.
      type: int
    repo_count:
      description: Number of repositories in the project.
      type: int
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    HarborError,
    harbor_argument_spec,
    project_view,
    read_as_user,
    run_module,
)


def admin_list(client, path, params=None):
    """A system-level list, or [] when the login user is not an administrator (HTTP 401 or 403)."""
    try:
        return client.list(path, params=params)
    except HarborError as e:
        if e.status not in (401, 403):
            raise
        return []


def list_projects(module, client):
    client.warn_if_untested()
    name = module.params['name']
    # A list cannot show that private projects are missing from it (Harbor
    # leaves them out for a moment after another client failed to log in as
    # this user), so the login is checked again after it. One named project
    # that was found needs no check.
    projects = read_as_user(
        client, lambda: [p for p in client.list('/projects') if name is None or p.get('name') == name],
        lambda found: name is not None and bool(found), 'the list of projects')
    registries = {}
    if any(p.get('registry_id') for p in projects):
        registries = dict((r['id'], r['name']) for r in admin_list(client, '/registries'))
    quotas = {}
    if projects:
        quotas = dict((q.get('ref', {}).get('id'), q) for q in admin_list(client, '/quotas', dict(reference='project')))
    out = [project_view(p, quotas.get(p.get('project_id')), registries) for p in projects]
    return dict(changed=False, projects=sorted(out, key=lambda p: (p['name'] or '', p['project_id'] or 0)))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: list_projects(module, client))


if __name__ == '__main__':
    main()
