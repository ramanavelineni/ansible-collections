#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: view_info
short_description: List the views (template tabs) in a Semaphore UI project
version_added: 0.1.0
description:
  - Lists a project's views in tab order, optionally only the one with a given title.
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
      - Only return views with this title.
    type: str
'''

EXAMPLES = r'''
- name: List the homelab project's views
  ramanavelineni.semaphoreui.view_info:
    project: homelab
  register: result
'''

RETURN = r'''
views:
  description: Matching views, sorted by position. C(type) is C(all) for the built-in view that lists every template.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      name: All
      position: 0
      hidden: false
      sort_column: ""
      sort_reverse: false
      type: all
      project_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_views(module, client):
    client.warn_if_untested()
    base = '/project/%d' % project_ref(client, module.params)[0]
    out = []
    for view in client.list(base + '/views'):
        if module.params['name'] is not None and view.get('title') != module.params['name']:
            continue
        out.append(dict(
            id=view.get('id'), name=view.get('title'), position=int(view.get('position') or 0),
            hidden=bool(view.get('hidden', False)), sort_column=view.get('sort_column') or '',
            sort_reverse=bool(view.get('sort_reverse', False)), type=view.get('type') or '',
            project_id=view.get('project_id')))
    return dict(changed=False, views=sorted(out, key=lambda v: (v['position'], v['name'] or '')))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str'), project_id=dict(type='int'), name=dict(type='str'))
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: list_views(module, client))


if __name__ == '__main__':
    main()
