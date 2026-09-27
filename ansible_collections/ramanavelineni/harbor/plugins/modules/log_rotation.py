#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: log_rotation
short_description: Manage Harbor's audit log rotation schedule
version_added: 0.1.0
description:
  - Sets, changes or removes the schedule that purges old audit log entries (Administration >
    Clean Up > Log Rotation), and what it purges.
  - Only the options you set are compared and changed; the others keep their current value.
  - The module never starts a purge run itself.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.harbor.auth
  - ramanavelineni.harbor.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
options:
  schedule:
    description:
      - When the purge runs. V(none) removes the schedule.
      - V(hourly), V(daily) and V(weekly) are the UI's presets (every hour, every day at 00:00,
        Sundays at 00:00, in the Harbor server's time zone). V(custom) runs at O(cron).
      - Leaving it unset keeps the current schedule; setting only O(cron) means V(custom).
    type: str
    choices: [none, hourly, daily, weekly, custom]
  cron:
    description:
      - Cron expression for V(custom), in Harbor's 6-field form
        (second minute hour day-of-month month day-of-week), for example C(0 0 6 * * *).
    type: str
  audit_retention_hour:
    description:
      - Audit log entries older than this many hours are purged (at most 240000).
      - Required when a schedule is first set.
    type: int
  include_event_types:
    description:
      - Which kinds of audit log entries are purged, for example C(create_artifact) or
        C(pull_artifact). The module checks them against the list the server reports.
      - Required when a schedule is first set.
    type: list
    elements: str
  dry_run:
    description:
      - Only log what would be purged.
    type: bool
notes:
  - Settings apply to the schedule, so they can only be set while there is one (or with
    O(schedule) in the same task).
'''

EXAMPLES = r'''
- name: Every day at 06:00, purge artifact events older than 30 days
  ramanavelineni.harbor.log_rotation:
    schedule: custom
    cron: "0 0 6 * * *"
    audit_retention_hour: 720
    include_event_types: [create_artifact, delete_artifact, pull_artifact]
'''

RETURN = r'''
log_rotation:
  description: The schedule after the change, or as it would be in check mode.
  returned: always
  type: dict
  contains:
    schedule:
      description: V(none), V(hourly), V(daily), V(weekly) or V(custom).
      type: str
    cron:
      description: The cron expression, empty without a schedule.
      type: str
    next_scheduled_time:
      description: When Harbor runs it next, as Harbor reports it.
      type: str
    audit_retention_hour:
      description: Retention in hours.
      type: int
    include_event_types:
      description: Kinds of entries purged.
      type: list
      elements: str
    dry_run:
      description: Whether the purge only logs.
      type: bool
  sample:
    schedule: custom
    cron: "0 0 6 * * *"
    next_scheduled_time: "2026-09-28T06:00:00.000Z"
    audit_retention_hour: 720
    include_event_types: [create_artifact, delete_artifact, pull_artifact]
    dry_run: false
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    run_module,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.schedule import (
    comparable,
    desired_timing,
    read_schedule,
    schedule_argument_spec,
    schedule_body,
    schedule_view,
)

PATH = '/system/purgeaudit/schedule'
PARAMETERS = ('audit_retention_hour', 'include_event_types', 'dry_run')
MAX_RETENTION_HOUR = 240000


def split_types(value):
    """include_event_types as Harbor stores it (a comma-separated string) -> list."""
    if isinstance(value, list):
        return sorted(set(value))
    return sorted(set(t for t in (value or '').split(',') if t))


def to_api(parameters):
    out = dict(parameters)
    if 'include_event_types' in out:
        out['include_event_types'] = ','.join(out['include_event_types'] or [])
    return out


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    if params['audit_retention_hour'] is not None and not 0 < params['audit_retention_hour'] <= MAX_RETENTION_HOUR:
        raise ValueError('audit_retention_hour must be between 1 and %d.' % MAX_RETENTION_HOUR)
    if params['include_event_types']:
        known = set(e.get('event_type') for e in client.get('/auditlog-exts/events') or [])
        unknown = sorted(set(params['include_event_types']) - known)
        if unknown:
            raise ValueError('Unknown event types %s; this server knows %s.'
                             % (', '.join(unknown), ', '.join(sorted(known))))

    timing, raw_params = read_schedule(client, PATH)
    current_params = dict(raw_params)
    if 'include_event_types' in current_params:
        current_params['include_event_types'] = split_types(current_params['include_event_types'])
    before = schedule_view(timing, current_params, PARAMETERS)

    kind, cron = desired_timing(params, timing)
    wanted = dict((name, params[name]) for name in PARAMETERS if params[name] is not None)
    if 'include_event_types' in wanted:
        # Harbor keeps them in the order sent; the order doesn't matter.
        wanted['include_event_types'] = split_types(wanted['include_event_types'])
    if kind == 'none' and wanted:
        raise ValueError('%s only apply to a schedule; there is none%s.'
                         % (', '.join(sorted(wanted)), '' if timing is None else ' after this change'))

    new_params = dict((k, v) for k, v in current_params.items() if k in PARAMETERS and v is not None)
    new_params.update(wanted)
    if kind != 'none':
        missing = [n for n in ('audit_retention_hour', 'include_event_types') if n not in new_params]
        if missing:
            raise ValueError('A log rotation schedule needs %s (Harbor requires them).' % ' and '.join(missing))
        after = schedule_view(dict(schedule=kind, cron=cron, next_scheduled_time=None), new_params, PARAMETERS)
    else:
        after = schedule_view(None, {}, PARAMETERS)

    if comparable(after) == comparable(before):
        return dict(changed=False, log_rotation=before, diff=dict(before=before, after=before))

    if not module.check_mode:
        # Harbor requires both parameters on every write, removing the
        # schedule included, so a removal sends the current ones back.
        body_params = to_api(new_params if kind != 'none' else current_params)
        client.put(PATH, schedule_body(kind, cron, body_params))
        timing, raw_params = read_schedule(client, PATH)
        current_params = dict(raw_params)
        if 'include_event_types' in current_params:
            current_params['include_event_types'] = split_types(current_params['include_event_types'])
        after = schedule_view(timing, current_params, PARAMETERS)
    return dict(changed=True, log_rotation=after, diff=dict(before=before, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(schedule_argument_spec())
    argument_spec.update(
        audit_retention_hour=dict(type='int'),
        include_event_types=dict(type='list', elements='str'),
        dry_run=dict(type='bool'),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
