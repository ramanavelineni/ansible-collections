#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: garbage_collection
short_description: Manage Harbor's garbage collection schedule
version_added: 0.1.0
description:
  - Sets, changes or removes the schedule of Harbor's garbage collection (Administration >
    Clean Up > Garbage Collection), and its settings.
  - Only the options you set are compared and changed; the others keep their current value. That
    includes settings this module has no option for, such as a dry run set through Harbor's API.
  - The module never starts a garbage collection run itself.
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
      - When garbage collection runs. V(none) removes the schedule.
      - V(hourly), V(daily) and V(weekly) are the UI's presets (every hour, every day at 00:00,
        Sundays at 00:00, in the Harbor server's time zone). V(custom) runs at O(cron).
      - Leaving it unset keeps the current schedule; setting only O(cron) means V(custom).
    type: str
    choices: [none, hourly, daily, weekly, custom]
  cron:
    description:
      - Cron expression for V(custom), in Harbor's 6-field form
        (second minute hour day-of-month month day-of-week), for example C(0 0 4 * * 0).
    type: str
  delete_untagged:
    description:
      - Also delete untagged artifacts.
    type: bool
  workers:
    description:
      - How many workers run the garbage collection in parallel, 1 to 10.
    type: int
  delete_tag:
    description:
      - Also delete tags that point to deleted artifacts. Harbor 2.15 and newer; Harbor 2.14 would
        ignore it, so the module fails when it is set there.
    type: bool
notes:
  - Settings apply to the schedule, so they can only be set while there is one (or with
    O(schedule) in the same task).
  - If Harbor reports a schedule of a type other than the choices of O(schedule), the module fails
    when it would have to write that schedule back. Set O(schedule) to replace it.
'''

EXAMPLES = r'''
- name: Garbage collection every Sunday at 04:00, untagged artifacts included
  ramanavelineni.harbor.garbage_collection:
    schedule: custom
    cron: "0 0 4 * * 0"
    delete_untagged: true
    workers: 2

- name: No scheduled garbage collection
  ramanavelineni.harbor.garbage_collection:
    schedule: none
'''

RETURN = r'''
garbage_collection:
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
    delete_untagged:
      description: Whether untagged artifacts are deleted too.
      type: bool
    workers:
      description: Number of workers.
      type: int
    delete_tag:
      description: Whether tags of deleted artifacts are deleted too (Harbor 2.15 and newer).
      type: bool
  sample:
    schedule: custom
    cron: "0 0 4 * * 0"
    next_scheduled_time: "2026-10-04T04:00:00.000Z"
    delete_untagged: true
    workers: 2
    delete_tag: false
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    run_module,
    server_minor,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.schedule import (
    carried_parameters,
    comparable,
    desired_timing,
    read_schedule,
    require_known_type,
    schedule_argument_spec,
    schedule_body,
    schedule_view,
)

PATH = '/system/gc/schedule'
PARAMETERS = ('delete_untagged', 'workers', 'delete_tag')


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    if params['delete_tag'] is not None and (server_minor(client) or (0, 0)) < (2, 15):
        raise ValueError('delete_tag needs Harbor 2.15 or newer; this server is %s.'
                         % client.info().get('harbor_version'))
    if params['workers'] is not None and not 1 <= params['workers'] <= 10:
        raise ValueError('workers must be between 1 and 10.')

    timing, current_params = read_schedule(client, PATH)
    before = schedule_view(timing, current_params, PARAMETERS)

    kind, cron = desired_timing(params, timing)
    wanted = dict((name, params[name]) for name in PARAMETERS if params[name] is not None)
    if kind == 'none' and wanted:
        raise ValueError('%s only apply to a schedule; there is none%s.'
                         % (', '.join(sorted(wanted)), '' if timing is None else ' after this change'))

    # Parameters this module has no option for go back as stored: Harbor
    # replaces them as a whole, and leaving one out would drop it.
    new_params = carried_parameters(current_params)
    new_params.update(wanted)
    if kind == 'none':
        after = schedule_view(None, {}, PARAMETERS)
    else:
        after = schedule_view(dict(schedule=kind, cron=cron, next_scheduled_time=None), new_params, PARAMETERS)

    if comparable(after) == comparable(before):
        return dict(changed=False, garbage_collection=before, diff=dict(before=before, after=before))

    require_known_type(kind)
    if not module.check_mode:
        # POST and PUT do the same for a schedule type: Harbor deletes the
        # schedule and creates it again. Type Manual would start a run now,
        # which this module never sends.
        client.put(PATH, schedule_body(kind, cron, None if kind == 'none' else new_params))
        timing, current_params = read_schedule(client, PATH)
        after = schedule_view(timing, current_params, PARAMETERS)
    return dict(changed=True, garbage_collection=after, diff=dict(before=before, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(schedule_argument_spec())
    argument_spec.update(
        delete_untagged=dict(type='bool'),
        workers=dict(type='int'),
        delete_tag=dict(type='bool'),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
