#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: scan_all_info
short_description: Read Harbor's Scan All schedule and latest scan metrics
version_added: 0.1.0
description:
  - Reads the schedule on which Harbor scans every artifact for vulnerabilities, and the metrics of
    the latest Scan All run (Administration > Interrogation Services > Vulnerability).
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
notes:
  - Harbor needs a default vulnerability scanner for this; without one the module fails saying so.
'''

EXAMPLES = r'''
- name: Scan All schedule and latest metrics
  ramanavelineni.harbor.scan_all_info:
  register: scan_all
'''

RETURN = r'''
scan_all:
  description: The schedule, as the scan_all module returns it.
  returned: always
  type: dict
  sample:
    schedule: custom
    cron: "0 0 5 * * 0"
    next_scheduled_time: null
metrics:
  description: Harbor's metrics of the latest Scan All run (total, completed, metrics by status, ongoing, trigger).
  returned: always
  type: dict
  sample:
    total: 40
    completed: 40
    metrics: {Success: 40}
    ongoing: false
    trigger: Schedule
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    HarborError,
    harbor_argument_spec,
    run_module,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.schedule import (
    NO_SCANNER,
    read_schedule,
    schedule_view,
)


def read(module, client):
    client.warn_if_untested()
    try:
        timing, dummy = read_schedule(client, '/system/scanAll/schedule')
        metrics = client.get('/scans/all/metrics') or {}
    except HarborError as e:
        if e.status == 412:
            raise ValueError(NO_SCANNER)
        raise
    return dict(changed=False, scan_all=schedule_view(timing, {}, ()), metrics=metrics)


def main():
    module = AnsibleModule(argument_spec=harbor_argument_spec(), supports_check_mode=True)
    run_module(module, lambda client: read(module, client))


if __name__ == '__main__':
    main()
