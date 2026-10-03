#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: log_rotation_info
short_description: Read Harbor's audit log rotation schedule and recent purges
version_added: 0.1.0
description:
  - Reads the audit log rotation schedule and settings, and the most recent purge runs
    (Administration > Clean Up > Log Rotation).
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
  runs:
    description:
      - How many of the most recent purge runs to return, newest first. V(0) returns none.
      - Harbor returns at most 100 runs per request; more than that are read in several requests.
    type: int
    default: 10
seealso:
  - module: ramanavelineni.harbor.log_rotation
    description: Manage the audit log rotation schedule.
'''

EXAMPLES = r'''
# The connection options (url, username, password) are left out of these examples. Set them once with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: Log rotation schedule
  ramanavelineni.harbor.log_rotation_info:
    runs: 0
  register: rotation
'''

RETURN = r'''
log_rotation:
  description: The schedule and its settings, as the log_rotation module returns them.
  returned: always
  type: dict
  sample:
    schedule: custom
    cron: "0 0 6 * * *"
    next_scheduled_time: "2026-09-28T06:00:00.000Z"
    audit_retention_hour: 720
    include_event_types: [create_artifact, delete_artifact]
    dry_run: false
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
runs:
  description: The most recent purge runs, newest first.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 4
      status: Success
      trigger: SCHEDULE
      parameters: {audit_retention_hour: 720, include_event_types: "create_artifact,delete_artifact"}
      creation_time: "2026-09-27T06:00:00.000Z"
      update_time: "2026-09-27T06:00:03.000Z"
  contains:
    id:
      description: Harbor's id of the run.
      type: int
    status:
      description: Status of the run as Harbor reports it, for example V(Success).
      type: str
    trigger:
      description: What started the run as Harbor reports it, for example V(SCHEDULE).
      type: str
    parameters:
      description: The settings the purge ran with, as Harbor recorded them.
      type: dict
    creation_time:
      description: When the run was created.
      type: str
    update_time:
      description: When the run was last updated.
      type: str
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    run_module,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.schedule import (
    LOG_ROTATION_PARAMETERS as PARAMETERS,
    read_schedule,
    recent_runs,
    schedule_view,
    split_types,
)


def read(module, client):
    client.warn_if_untested()
    if module.params['runs'] < 0:
        raise ValueError('runs must be 0 or more.')
    timing, parameters = read_schedule(client, '/system/purgeaudit/schedule')
    if 'include_event_types' in parameters:
        parameters['include_event_types'] = split_types(parameters['include_event_types'])
    return dict(changed=False, log_rotation=schedule_view(timing, parameters, PARAMETERS),
                runs=recent_runs(client, '/system/purgeaudit', module.params['runs']))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(runs=dict(type='int', default=10))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: read(module, client))


if __name__ == '__main__':
    main()
