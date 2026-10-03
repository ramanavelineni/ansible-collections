#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: garbage_collection_info
short_description: Read Harbor's garbage collection schedule and recent runs
version_added: 0.1.0
description:
  - Reads the garbage collection schedule and settings, and the most recent garbage collection
    runs (Administration > Clean Up > Garbage Collection).
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
      - How many of the most recent runs to return, newest first. V(0) returns none.
      - Harbor returns at most 100 runs per request; more than that are read in several requests.
    type: int
    default: 10
seealso:
  - module: ramanavelineni.harbor.garbage_collection
    description: Manage the garbage collection schedule.
'''

EXAMPLES = r'''
# The connection options (url, username, password) are left out of these examples. Set them once with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: Last garbage collection runs
  ramanavelineni.harbor.garbage_collection_info:
    runs: 3
  register: gc
'''

RETURN = r'''
garbage_collection:
  description: The schedule and its settings, as the garbage_collection module returns them.
  returned: always
  type: dict
  sample:
    schedule: custom
    cron: "0 0 4 * * 0"
    next_scheduled_time: "2026-10-04T04:00:00.000Z"
    delete_untagged: true
    workers: 2
    delete_tag: false
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
    delete_untagged:
      description: Whether untagged artifacts are deleted too.
      type: bool
    workers:
      description: Number of workers.
      type: int
    delete_tag:
      description: Whether tags of deleted artifacts are deleted too (Harbor 2.15 and newer).
      type: bool
runs:
  description: The most recent runs, newest first.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 12
      status: Success
      trigger: SCHEDULE
      parameters: {delete_untagged: true, workers: 2}
      creation_time: "2026-09-27T04:00:00.000Z"
      update_time: "2026-09-27T04:00:12.000Z"
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
      description: The settings the garbage collection ran with, as Harbor recorded them.
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
    GC_PARAMETERS as PARAMETERS,
    read_schedule,
    recent_runs,
    schedule_view,
)


def read(module, client):
    client.warn_if_untested()
    if module.params['runs'] < 0:
        raise ValueError('runs must be 0 or more.')
    timing, parameters = read_schedule(client, '/system/gc/schedule')
    return dict(changed=False, garbage_collection=schedule_view(timing, parameters, PARAMETERS),
                runs=recent_runs(client, '/system/gc', module.params['runs']))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(runs=dict(type='int', default=10))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: read(module, client))


if __name__ == '__main__':
    main()
