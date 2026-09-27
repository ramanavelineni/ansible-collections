#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: schedule_info
short_description: List the schedules in a Semaphore UI project
version_added: 0.1.0
description:
  - Lists a project's schedules, including commit pollers (which Semaphore's own project list
    leaves out), optionally only the one with a given name.
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
      - Only return schedules with this name.
    type: str
'''

EXAMPLES = r'''
- name: List the homelab project's schedules
  ramanavelineni.semaphoreui.schedule_info:
    project: homelab
  register: result
'''

RETURN = r'''
schedules:
  description: Matching schedules, sorted by name. C(kind) is C(cron), C(poller) or C(run_at).
  returned: always
  type: list
  elements: dict
  sample:
    - id: 3
      name: reconcile-on-push
      template: semaphore_config
      kind: poller
      cron: "*/5 * * * *"
      repository: ansible
      run_at: null
      delete_after_run: false
      active: true
      project_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    all_schedules,
    resolve_project,
    run_module,
    schedule_view,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_schedules(module, client):
    client.warn_if_untested()
    base = '/project/%d' % resolve_project(client, module.params['project'])
    templates = client.list(base + '/templates')
    tpl_names = dict((t['id'], t['name']) for t in templates)
    repo_names = dict((r['id'], r['name']) for r in client.list(base + '/repositories'))
    out = [schedule_view(s, repo_names, tpl_names) for s in all_schedules(client, base, templates)
           if module.params['name'] is None or s.get('name') == module.params['name']]
    return dict(changed=False, schedules=sorted(out, key=lambda s: (s['name'] or '', s['id'] or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str', required=True), name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True, **semaphore_module_kwargs())
    run_module(module, lambda client: list_schedules(module, client))


if __name__ == '__main__':
    main()
