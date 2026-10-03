#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: runner
short_description: Manage Semaphore UI runners
version_added: 0.1.0
description:
  - Creates, updates or deletes a runner, found by its name. Without O(project) the runner is a
    global runner (administrators only); with O(project) it belongs to that project.
  - Only the options you set are compared and changed; the others keep their current value.
  - A new runner has no credentials. The module asks Semaphore for a one-time registration token
    right after creating it and returns it as RV(registration_token); the runner uses it to
    register. The token is valid for one hour. O(regenerate_token=true) gets a fresh one later.
  - Creating a runner and asking for its token are two requests. The token request is repeated on
    a transient failure (see O(retries)). If it still fails, the module deletes the runner it just
    created and fails, so that the next run starts over and returns a token.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
options:
  name:
    description:
      - Name of the runner. Runners are looked up by this name, among the global runners or among
        the project's runners.
    type: str
    required: true
  project:
    description:
      - Name of the project the runner belongs to. Leave it unset for a global runner.
      - Project runners need Semaphore Pro. A Community server lists none and refuses to create one
        (HTTP 403, "Your plan does not allow adding more runners"), and the module fails with that message.
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
  state:
    description:
      - V(present) creates the runner or updates it to match.
      - V(absent) deletes it.
    type: str
    choices: [present, absent]
    default: present
  max_parallel_tasks:
    description:
      - How many tasks the runner runs at once. V(0) means no limit.
    type: int
  active:
    description:
      - Whether the runner takes tasks. Defaults to V(true) for a new runner.
    type: bool
  tags:
    description:
      - Tags that templates can require with their runner tag. Replaces the runner's current tags;
        the order does not matter.
    type: list
    elements: str
  webhook:
    description:
      - URL Semaphore calls when the runner is needed.
    type: str
  is_default:
    description:
      - Whether the runner also takes tasks of templates that require no runner tag.
    type: bool
  regenerate_token:
    description:
      - Get a new one-time registration token for an existing runner and return it.
      - B(If the runner is already registered, this resets it:) its credentials are cleared and it
        has to register again with the new token before it takes tasks.
      - In check mode no token is requested, and RV(runner) shows the runner as it would be
        afterwards (C(registered) is V(false)).
    type: bool
    default: false
notes:
  - The registration token is returned in the task result. Set C(no_log) on the task so it is
    not shown in the output.
  - Semaphore's update replaces every field of a runner, so the module always sends the whole
    runner with the changes applied.
seealso:
  - module: ramanavelineni.semaphoreui.runner_info
    description: Reads runners without changing them.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Global runner, with its registration token
  ramanavelineni.semaphoreui.runner:
    name: lxc-runner-1
    max_parallel_tasks: 2
    tags: [lxc]
  register: runner
  no_log: true

- name: Register it (on the runner host)
  ansible.builtin.command: semaphore runner register --stdin-registration-token
  args:
    stdin: "{{ runner.registration_token }}"
  when: runner.registration_token
  no_log: true

- name: New registration token for a runner that lost its credentials
  ramanavelineni.semaphoreui.runner:
    name: lxc-runner-1
    regenerate_token: true
  register: runner
  no_log: true
'''

RETURN = r'''
runner:
  description:
    - The runner after the change, or as it would be in check mode.
    - Empty after a deletion.
  returned: always
  type: dict
  contains:
    id:
      description: Runner id.
      type: int
    name:
      description: Name of the runner.
      type: str
    project:
      description: Name of the project the runner belongs to. Null for a global runner.
      type: str
    max_parallel_tasks:
      description: How many tasks the runner runs at once, V(0) for no limit.
      type: int
    active:
      description: Whether the runner takes tasks.
      type: bool
    tags:
      description: The runner's tags, sorted.
      type: list
      elements: str
    webhook:
      description: URL Semaphore calls when the runner is needed. Empty when not set.
      type: str
    is_default:
      description: Whether the runner also takes tasks of templates that require no runner tag.
      type: bool
    registered:
      description: Whether a runner process has registered with its token.
      type: bool
    status:
      description: Status as Semaphore 2.19 and newer report it, for example V(offline). Empty on 2.18.
      type: str
  sample:
    id: 1
    name: lxc-runner-1
    project: null
    max_parallel_tasks: 2
    active: true
    tags: [lxc]
    webhook: ""
    is_default: false
    registered: false
    status: offline
registration_token:
  description:
    - One-time registration token, valid for one hour.
    - Empty unless the runner was created or O(regenerate_token=true) was set (and not in check mode).
  returned: always
  type: str
  sample: smrs_...
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    SemaphoreError,
    find_by_name,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)

MANAGED = ('max_parallel_tasks', 'active', 'tags', 'webhook', 'is_default')


def normalize(runner, project):
    return dict(
        id=runner.get('id'), name=runner.get('name'), project=project,
        max_parallel_tasks=int(runner.get('max_parallel_tasks') or 0),
        active=bool(runner.get('active', False)),
        tags=sorted(set(runner.get('tags') or [])),
        webhook=runner.get('webhook') or '',
        is_default=bool(runner.get('is_default', False)),
        registered=bool(runner.get('registered', False)),
        status=runner.get('status') or '',
    )


def body_for(state, project_id):
    """The whole runner, as the update and create endpoints take it."""
    body = dict(name=state['name'], max_parallel_tasks=state['max_parallel_tasks'], active=state['active'],
                tags=state['tags'], webhook=state['webhook'], is_default=state['is_default'])
    if project_id is not None:
        body['project_id'] = project_id
    return body


def registration_token(client, path):
    """A new one-time registration token for the runner at `path`.

    Repeated on a transient failure, unlike other POSTs: every answer is a new
    token and only the last one is handed out, so a token whose answer got lost
    is one nobody ever had.
    """
    token = client.request('POST', path + '/registration-token', expected=(200,), retry=True) or {}
    return token.get('registration_token') or ''


def token_for_new_runner(module, client, path, name):
    """The new runner's token. If it can't be had, the runner goes again.

    A runner left behind without its token would look finished to the next run:
    found by name, nothing to change, no token returned.
    """
    try:
        return registration_token(client, path)
    except SemaphoreError as error:
        try:
            client.delete(path)
        except SemaphoreError as cleanup:
            module.fail_json(
                msg='Runner %r was created, but its registration token could not be fetched: %s. Deleting the '
                    'runner again failed too: %s. It exists without a token; run the task again with '
                    'regenerate_token: true to get one.' % (name, error.message(), cleanup.message()),
                request_details=error.details())
        module.fail_json(
            msg='Runner %r was created, but its registration token could not be fetched: %s. The runner was '
                'deleted again, so the next run starts over.' % (name, error.message()),
            request_details=error.details())


def ensure(module, client):
    params = module.params
    client.warn_if_untested()

    base = ''
    project_id, project = project_ref(client, params, missing_ok=params['state'] == 'absent')
    if params['project'] is not None or params['project_id'] is not None:
        if project_id is None:
            # The project is gone, and everything in it went with it.
            return dict(changed=False, runner={}, registration_token='', diff=dict(before={}, after={}))
        base = '/project/%d' % project_id
    runners = client.list(base + '/runners')
    if project_id is None:
        # The global list includes project runners too.
        runners = [r for r in runners if r.get('project_id') is None]
    current = find_by_name(runners, params['name'], 'runner')
    result = dict(changed=False, runner={}, registration_token='')

    if params['state'] == 'absent':
        if not current:
            result.update(diff=dict(before={}, after={}))
            return result
        before = normalize(current, project)
        if not module.check_mode:
            client.delete('%s/runners/%d' % (base, current['id']))
        result.update(changed=True, diff=dict(before=before, after={}))
        return result

    desired = dict((k, params[k]) for k in MANAGED)
    if desired['tags'] is not None:
        desired['tags'] = sorted(set(desired['tags']))

    if not current:
        after = normalize(dict(name=params['name'], active=True), project)
        after.update((k, v) for k, v in desired.items() if v is not None)
        after.pop('id')
        if not module.check_mode:
            created = client.post(base + '/runners', body_for(after, project_id), expected=(200, 201))
            after = normalize(created, project)
            result['registration_token'] = token_for_new_runner(
                module, client, '%s/runners/%d' % (base, created['id']), params['name'])
        result.update(changed=True, runner=after, diff=dict(before={}, after=after))
        return result

    before = normalize(current, project)
    after = dict(before)
    after.update((k, v) for k, v in desired.items() if v is not None)
    fields_changed = any(after[k] != before[k] for k in MANAGED)

    if fields_changed and not module.check_mode:
        client.put('%s/runners/%d' % (base, current['id']), body_for(after, project_id))
    if params['regenerate_token']:
        if before['registered']:
            module.warn('Runner %r was registered; the new registration token resets it, and it has to '
                        'register again before it takes tasks.' % params['name'])
        if not module.check_mode:
            result['registration_token'] = registration_token(client, '%s/runners/%d' % (base, current['id']))
        # A new token clears the runner's credentials. Check mode says so too.
        after['registered'] = False
    result.update(changed=fields_changed or params['regenerate_token'], runner=after,
                  diff=dict(before=before, after=after))
    return result


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        project=dict(type='str'),
        project_id=dict(type='int'),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        max_parallel_tasks=dict(type='int'),
        active=dict(type='bool'),
        tags=dict(type='list', elements='str'),
        webhook=dict(type='str'),
        is_default=dict(type='bool'),
        regenerate_token=dict(type='bool', default=False, no_log=False),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True,
                           **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS]))
    run_module(module, lambda client: ensure(module, client), placeholder=dict(runner={}, registration_token=''))


if __name__ == '__main__':
    main()
