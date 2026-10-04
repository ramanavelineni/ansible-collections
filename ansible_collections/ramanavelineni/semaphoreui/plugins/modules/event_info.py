#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: event_info
short_description: Read the activity log of Semaphore UI
version_added: 0.4.0
description:
  - Lists the events Semaphore recorded, newest first; the B(Activity) page of the UI shows the same. An
    event says who created, changed or deleted what, and when.
  - With O(project) or O(project_id), the events of that project. Without, the events of every project the
    user that logs in is a member of, and those that belong to no project.
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
      - Name of the project whose events to list.
      - Mutually exclusive with O(project_id).
    type: str
  project_id:
    description:
      - Id of the project, as an alternative to O(project).
      - With it the list of projects is not read, so a project is found on a server with 200 or more
        projects too. Semaphore cuts that list off at 200, and O(project) fails there.
      - Mutually exclusive with O(project).
    type: int
  limit:
    description:
      - How many events to return at most, counted from the newest. V(0) returns every event the server has,
        which can be a long list.
      - Semaphore has no paging for events. Up to V(200) the module asks for the newest 200 and returns the
        first O(limit) of them; above that, and for V(0), it asks for all of them.
    type: int
    default: 200
notes:
  - Semaphore records the events itself and there is no way to add, change or delete one.
  - An event keeps the id of what it is about, not its name; the name is usually in C(description). Semaphore
    fills C(object_name) only for a task, with the playbook it ran.
seealso:
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: The last twenty events of the homelab project
  ramanavelineni.semaphoreui.event_info:
    project: homelab
    limit: 20
  register: activity

- name: Everything the server recorded
  ramanavelineni.semaphoreui.event_info:
    limit: 0
  register: all_activity
'''

RETURN = r'''
events:
  description: The events, newest first.
  returned: always
  type: list
  elements: dict
  contains:
    created:
      description: When it happened, in UTC.
      type: str
    description:
      description: What happened, in Semaphore's words, for example C(Environment vars created).
      type: str
    object_type:
      description:
        - Kind of object the event is about, as Semaphore names it, for example V(template), V(key),
          V(environment) (a variable group) or V(task). Empty when the event names none.
      type: str
    object_id:
      description: Id of that object. Null when the event names none.
      type: int
    object_name:
      description: For a task, the playbook it ran. Empty for every other kind of object, and for a task that is gone.
      type: str
    project_id:
      description: Id of the project the event belongs to. Null for an event outside any project.
      type: int
    project:
      description: Name of that project. Null for an event outside any project, or when the project is gone.
      type: str
    user_id:
      description: Id of the user that caused the event. Null when no user did.
      type: int
    username:
      description: Login name of that user. Null when no user did, or the user is gone.
      type: str
    integration_id:
      description: Id of the integration that caused the event. Null when none did.
      type: int
  sample:
    - created: "2026-10-04T15:52:35.830647Z"
      description: Schedule ID 48 created
      object_type: schedule
      object_id: 48
      object_name: ""
      project_id: 3
      project: homelab
      user_id: 1
      username: admin
      integration_id: null
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    normalize_time,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)

# What Semaphore's /events/last returns at most.
LAST = 200


def view(event):
    return dict(
        created=normalize_time(event.get('created')),
        description=event.get('description') or '',
        object_type=event.get('object_type') or '',
        object_id=event.get('object_id'),
        object_name=event.get('object_name') or '',
        project_id=event.get('project_id'),
        project=event.get('project_name'),
        user_id=event.get('user_id'),
        username=event.get('username'),
        integration_id=event.get('integration_id'),
    )


def list_events(module, client):
    params = module.params
    client.warn_if_untested()
    limit = params['limit']
    if limit < 0:
        raise ValueError('limit must be 0 (every event) or more. Got %d.' % limit)
    project_id = project_ref(client, params)[0]
    base = '/project/%d' % project_id if project_id is not None else ''
    events = client.list(base + ('/events/last' if 0 < limit <= LAST else '/events'))
    if limit:
        events = events[:limit]
    return dict(changed=False, events=[view(e) for e in events])


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str'), project_id=dict(type='int'), limit=dict(type='int', default=200))
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: list_events(module, client))


if __name__ == '__main__':
    main()
