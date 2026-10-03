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
      - Only return schedules with this name.
    type: str
seealso:
  - module: ramanavelineni.semaphoreui.schedule
    description: Creates, changes and deletes schedules.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

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
  contains:
    id:
      description: Schedule id.
      type: int
    name:
      description: Name of the schedule.
      type: str
    template:
      description: Name of the template the schedule starts.
      type: str
    kind:
      description: V(cron) for a cron schedule, V(poller) for a commit poller, V(run_at) for a single run.
      type: str
    cron:
      description: Cron expression. Empty when the schedule has none.
      type: str
    repository:
      description: Name of the repository a commit poller watches. Null for the other kinds.
      type: str
    run_at:
      description: Time of a single run, in UTC (C(2026-10-01T03:00:00Z)). Null for the other kinds.
      type: str
    delete_after_run:
      description: Whether a run-at schedule is deleted once it has run.
      type: bool
    active:
      description: Whether the schedule runs.
      type: bool
    project_id:
      description: Id of the project.
      type: int
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
    PROJECT_OPTIONS,
    all_schedules,
    project_ref,
    run_module,
    schedule_view,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_schedules(module, client):
    client.warn_if_untested()
    base = '/project/%d' % project_ref(client, module.params)[0]
    templates = client.list(base + '/templates')
    tpl_names = dict((t['id'], t['name']) for t in templates)
    repo_names = dict((r['id'], r['name']) for r in client.list(base + '/repositories'))
    out = [schedule_view(s, repo_names, tpl_names) for s in all_schedules(client, base, templates)
           if module.params['name'] is None or s.get('name') == module.params['name']]
    return dict(changed=False, schedules=sorted(out, key=lambda s: (s['name'] or '', s['id'] or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str'), project_id=dict(type='int'), name=dict(type='str'))
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: list_schedules(module, client))


if __name__ == '__main__':
    main()
