#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: scan_all
short_description: Manage Harbor's scheduled vulnerability scan of all artifacts
version_added: 0.1.0
description:
  - Sets, changes or removes the schedule on which Harbor scans every artifact for
    vulnerabilities (Administration > Interrogation Services > Vulnerability > Scan All).
  - The module never starts a scan itself.
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
      - When the scan runs. V(none) removes the schedule.
      - V(hourly), V(daily) and V(weekly) are the UI's presets (every hour, every day at 00:00,
        Sundays at 00:00, in the Harbor server's time zone). V(custom) runs at O(cron).
      - Setting only O(cron) means V(custom).
    type: str
    choices: [none, hourly, daily, weekly, custom]
  cron:
    description:
      - Cron expression for V(custom), in Harbor's 6-field form
        (second minute hour day-of-month month day-of-week), for example C(0 0 5 * * 0).
    type: str
notes:
  - Harbor needs a default vulnerability scanner (such as Trivy) for this. Without one it refuses
    every Scan All request, reading the schedule included, and the module fails saying so.
'''

EXAMPLES = r'''
- name: Scan everything on Sundays at 05:00
  ramanavelineni.harbor.scan_all:
    schedule: custom
    cron: "0 0 5 * * 0"
'''

RETURN = r'''
scan_all:
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
      description: Always null; Harbor doesn't report it for this schedule.
      type: str
  sample:
    schedule: custom
    cron: "0 0 5 * * 0"
    next_scheduled_time: null
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    HarborError,
    harbor_argument_spec,
    run_module,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.schedule import (
    NO_SCANNER,
    comparable,
    desired_timing,
    read_schedule,
    schedule_argument_spec,
    schedule_body,
    schedule_view,
)

PATH = '/system/scanAll/schedule'


def read(client):
    try:
        return read_schedule(client, PATH)
    except HarborError as e:
        if e.status == 412:
            raise ValueError(NO_SCANNER)
        raise


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    if params['schedule'] is None and params['cron'] is None:
        raise ValueError('Set schedule (or cron).')

    timing, dummy = read(client)
    before = schedule_view(timing, {}, ())
    kind, cron = desired_timing(params, timing)
    after = schedule_view(None if kind == 'none' else dict(schedule=kind, cron=cron, next_scheduled_time=None), {}, ())

    if comparable(after) == comparable(before):
        return dict(changed=False, scan_all=before, diff=dict(before=before, after=before))

    if not module.check_mode:
        # PUT creates, replaces or (type None) removes the schedule; POST
        # would refuse while one exists, and type Manual would scan now.
        client.put(PATH, schedule_body(kind, cron))
        timing, dummy = read(client)
        after = schedule_view(timing, {}, ())
    return dict(changed=True, scan_all=after, diff=dict(before=before, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(schedule_argument_spec())
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
