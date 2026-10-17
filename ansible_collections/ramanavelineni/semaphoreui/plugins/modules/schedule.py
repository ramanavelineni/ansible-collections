#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: schedule
short_description: Manage schedules in a Semaphore UI project
version_added: 0.1.0
description:
  - Creates, updates or deletes a schedule that starts a template's tasks, found by its name
    within the project.
  - A schedule is one of three kinds. A B(cron) schedule runs on every tick of O(cron). A B(commit
    poller) (O(cron) with O(repository)) fetches that repository's branch on every tick and runs
    the template only when the commit changed. A B(run-at) schedule (O(run_at)) runs once.
  - Only the options you set are compared and changed; the others keep their current value.
    Task-parameter overrides set on the schedule in Semaphore are kept as they are.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
  - ramanavelineni.semaphoreui.project
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
options:
  project_id:
    version_added: 0.3.0
  name:
    description:
      - Name of the schedule. Schedules are looked up by this name across the whole project, so it
        must be unique there.
    type: str
    required: true
  state:
    description:
      - V(present) creates the schedule or updates it to match.
      - V(absent) deletes it. This is also how to stop a commit poller.
    type: str
    choices: [present, absent]
    default: present
  template:
    description:
      - Name of the template the schedule starts. Required to create a schedule.
    type: str
  cron:
    description:
      - Cron expression (minute hour day-of-month month day-of-week), for example C(0 3 * * *).
        Descriptors such as C(@every 1h) work too.
      - For a commit poller this is how often the repository is checked.
      - Mutually exclusive with O(run_at).
    type: str
  repository:
    description:
      - Name of the repository to poll, which makes the schedule a commit poller.
      - An empty string turns a poller back into an ordinary cron schedule.
      - Semaphore runs a commit poller's first tick after it is created or changed in any way.
    type: str
  run_at:
    description:
      - Date and time (ISO 8601, for example C(2026-10-01T03:00:00Z)) to run the template once.
        It must be in the future when it is set. Semaphore refuses a time in the past.
      - Once the time has passed, Semaphore deactivates the schedule, or deletes it with
        O(delete_after_run=true). A later run of the same task then reports no change and warns,
        when the schedule is missing or inactive. A schedule that never existed looks the same as one
        that was deleted after its run, so a past O(run_at) does not create it either.
      - A past O(run_at) for a schedule that is still active fails when something would change, as
        Semaphore would refuse the update.
      - The value must name a time zone, C(Z) or an offset such as C(+02:00). It is sent to
        Semaphore in UTC, so C(2026-10-01T05:00:00+02:00) and C(2026-10-01T03:00:00Z) are the same
        schedule. A value that is not a date and time, or has no time zone, fails before anything
        is changed.
      - An unquoted YAML timestamp with a time zone works as well.
      - Mutually exclusive with O(cron).
    type: str
  delete_after_run:
    description:
      - For a run-at schedule, delete the schedule once it has run.
    type: bool
  active:
    description:
      - Whether the schedule runs. Defaults to V(true) for a new schedule.
      - Semaphore ignores V(false) for a commit poller (it keeps running), so the module fails
        instead of storing it. Use O(state=absent) to stop a poller.
    type: bool
seealso:
  - module: ramanavelineni.semaphoreui.schedule_info
    description: Reads schedules without changing them.
  - module: ramanavelineni.semaphoreui.template
    description: Manages the template a schedule starts.
  - module: ramanavelineni.semaphoreui.repository
    description: Manages the repository a commit poller watches.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Nightly run
  ramanavelineni.semaphoreui.schedule:
    project: homelab
    name: nightly-os-hardening
    template: os_hardening
    cron: "0 3 * * *"

- name: Run whenever main moves (checked every 5 minutes)
  ramanavelineni.semaphoreui.schedule:
    project: homelab
    name: reconcile-on-push
    template: semaphore_config
    repository: ansible
    cron: "*/5 * * * *"

# Once the time has passed and the schedule is deleted, running this task again reports no change.
- name: Run once
  ramanavelineni.semaphoreui.schedule:
    project: homelab
    name: one-off-upgrade
    template: upgrade
    run_at: "2026-10-01T03:00:00Z"
    delete_after_run: true
'''

RETURN = r'''
schedule:
  description:
    - The schedule after the change, or as it would be in check mode.
    - Empty after a deletion, and for a past O(run_at) whose schedule does not exist.
  returned: always
  type: dict
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
    id: 3
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

from datetime import datetime, timezone

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    MissingReference,
    PROJECT_REQUIRED,
    all_schedules,
    find_by_name,
    normalize_time,
    parse_time,
    project_argument_spec,
    project_ref,
    run_module,
    schedule_view as view,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def validate(params):
    # That cron and run_at exclude each other is in the argument spec.
    if params['run_at'] is not None and params['repository']:
        raise ValueError('A run-at schedule cannot poll a repository.')
    if params['run_at'] is not None:
        moment = parse_time(params['run_at'])
        if moment is None or moment.tzinfo is None:
            raise ValueError(
                'run_at %r is not a date and time with a time zone. Use ISO 8601 with Z or an offset, for '
                'example 2026-10-01T03:00:00Z or 2026-10-01T05:00:00+02:00.' % params['run_at'])


def ensure(module, client):
    params = module.params
    validate(params)
    client.warn_if_untested()

    project_id, project = project_ref(client, params, missing_ok=params['state'] == 'absent')
    if project_id is None:
        # The project is gone, and everything in it went with it.
        return dict(changed=False, schedule={}, diff=dict(before={}, after={}))
    base = '/project/%d' % project_id
    templates = client.list(base + '/templates')
    repositories = client.list(base + '/repositories')
    tpl_names = dict((t['id'], t['name']) for t in templates)
    repo_names = dict((r['id'], r['name']) for r in repositories)
    current = find_by_name(all_schedules(client, base, templates, name=params['name']), params['name'], 'schedule')

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, schedule={}, diff=dict(before={}, after={}))
        before = view(current, repo_names, tpl_names)
        if not module.check_mode:
            client.delete('%s/schedules/%d' % (base, current['id']))
        return dict(changed=True, schedule={}, diff=dict(before=before, after={}))

    past = params['run_at'] is not None and parse_time(params['run_at']) <= datetime.now(timezone.utc)
    if past and not (current and current.get('active')):
        # Semaphore refuses a past run_at, and after the run it deactivates the schedule or
        # deletes it (services/schedules/SchedulePool.go). Taken as settled, so that the task
        # that created a one-time schedule does not fail on every later run.
        if current:
            module.warn('Schedule %r is inactive and its run_at %s is in the past, so it is left as it is. '
                        'Give a run_at in the future to run it again.' % (params['name'], params['run_at']))
            before = view(current, repo_names, tpl_names)
        else:
            module.warn('Schedule %r does not exist and its run_at %s is in the past. It is taken as a one-time '
                        'schedule that already ran and was deleted, and is not created. A schedule that never '
                        'existed looks the same: give a run_at in the future to create it.'
                        % (params['name'], params['run_at']))
            before = {}
        return dict(changed=False, schedule=before, diff=dict(before=before, after=before))

    def ref(what, items, name):
        found = find_by_name(items, name, what)
        if found is None:
            raise MissingReference('%s %r does not exist in project %r.' % (what.capitalize(), name, project))
        return found['id']

    def make_body(base_obj):
        body = dict(base_obj) if base_obj else dict(active=True, delete_after_run=False, cron_format='', type='')
        body.pop('tpl_name', None)
        body.update(project_id=project_id, name=params['name'])
        if params['template'] is not None:
            body['template_id'] = ref('template', templates, params['template'])
        if params['run_at'] is not None:
            # In UTC, the form Semaphore itself returns. As typed, a value YAML read as a
            # timestamp would go out with a space where the T belongs.
            body.update(type='run_at', run_at=normalize_time(params['run_at']), cron_format='', repository_id=None)
        if params['cron'] is not None:
            body.update(type='', cron_format=params['cron'], run_at=None)
        if params['repository'] is not None:
            body['repository_id'] = ref('repository', repositories, params['repository']) if params['repository'] else None
        for key in ('active', 'delete_after_run'):
            if params[key] is not None:
                body[key] = params[key]
        return body

    body = make_body(current)
    after = view(body, repo_names, tpl_names)
    if after['kind'] == 'poller' and not after['active']:
        raise ValueError(
            'Schedule %r is a commit poller, and Semaphore runs pollers whether or not they are active, '
            'so active: false would not stop it. Use state: absent to stop it, or repository: "" to make it '
            'an ordinary cron schedule.' % params['name'])

    if not current:
        missing = []
        if params['template'] is None:
            missing.append('template')
        if params['cron'] is None and params['run_at'] is None:
            missing.append('cron or run_at')
        if missing:
            raise ValueError('Creating schedule %r needs %s.' % (params['name'], ', '.join(missing)))
        after.pop('id')
        if not module.check_mode:
            after = view(client.post(base + '/schedules', body), repo_names, tpl_names)
        return dict(changed=True, schedule=after, diff=dict(before={}, after=after))

    before = view(current, repo_names, tpl_names)
    if after == before:
        return dict(changed=False, schedule=before, diff=dict(before=before, after=before))
    if past:
        raise ValueError('run_at %s is in the past, and Semaphore refuses to store schedule %r with it. '
                         'Give a run_at in the future.' % (params['run_at'], params['name']))
    if not module.check_mode:
        # The update writes every column and unlinks task-parameter overrides
        # missing from the body. The lists leave those out, so the schedule
        # is read on its own and goes back with the changes applied.
        full = client.get('%s/schedules/%d' % (base, current['id'])) or current
        client.put('%s/schedules/%d' % (base, current['id']), make_body(full))
    return dict(changed=True, schedule=after, diff=dict(before=before, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project_argument_spec(),
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        template=dict(type='str'),
        cron=dict(type='str'),
        repository=dict(type='str'),
        run_at=dict(type='str'),
        delete_after_run=dict(type='bool'),
        active=dict(type='bool'),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True,
                           **semaphore_module_kwargs(project=PROJECT_REQUIRED, mutually_exclusive=[('cron', 'run_at')]))
    run_module(module, lambda client: ensure(module, client), placeholder=dict(schedule={}))


if __name__ == '__main__':
    main()
