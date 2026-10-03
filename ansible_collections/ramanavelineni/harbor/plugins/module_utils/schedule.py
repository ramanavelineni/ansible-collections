# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Shared handling of Harbor's system job schedules (GC, scan all, log rotation).

All three live at /system/<job>/schedule with one body shape:
{"schedule": {"type": T, "cron": "..."}, "parameters": {...}}. T "None" removes
the schedule; T "Manual" starts a run immediately and is never sent. A type
Harbor reports that is none of SCHEDULE_TYPES is shown as it is (lower-cased)
and refused when a write would have to send it back.
"""

import json

# The UI's presets and the cron each one stands for (Harbor's 6-field cron:
# second minute hour day-of-month month day-of-week).
PRESET_CRON = dict(hourly='0 0 * * * *', daily='0 0 0 * * *', weekly='0 0 0 * * 0')
SCHEDULE_TYPES = ('none', 'hourly', 'daily', 'weekly', 'custom')
API_TYPE = dict(none='None', hourly='Hourly', daily='Daily', weekly='Weekly', custom='Custom')

# Attributes Harbor keeps next to a schedule's parameters that are not
# parameters of the job. redis_url_reg is Harbor's internal Redis URL, which
# may carry a password: Harbor 2.14 returns it, 2.15 strips it.
INTERNAL_PARAMETERS = ('redis_url_reg', 'time_window')

# The run history is read in pages of at most this many, Harbor's largest page.
RUNS_PAGE_SIZE = 100


def schedule_argument_spec():
    """The options every schedule module takes."""
    return dict(
        schedule=dict(type='str', choices=list(SCHEDULE_TYPES)),
        cron=dict(type='str'),
    )


def parse_parameters(raw):
    """A schedule's parameters as a dict, from a dict or a JSON string."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raw = {}
    params = dict(raw or {})
    for key in INTERNAL_PARAMETERS:
        params.pop(key, None)
    return params


def read_schedule(client, path):
    """(timing, parameters) of the schedule at `path`; timing is None when there is none.

    Harbor answers 200 with an empty body when a job has no schedule.
    timing is dict(schedule=<lower-case type>, cron=..., next_scheduled_time=...).
    """
    body = client.get(path)
    if not body or not (body.get('schedule') or {}).get('type'):
        return None, {}
    sched = body['schedule']
    timing = dict(schedule=sched.get('type', '').lower(), cron=sched.get('cron') or '',
                  next_scheduled_time=sched.get('next_scheduled_time'))
    raw = body.get('job_parameters') if 'job_parameters' in body else body.get('parameters')
    return timing, parse_parameters(raw)


def desired_timing(params, current):
    """The (schedule, cron) the caller wants, or the current ones when unset.

    Fails when the options don't make a schedule: custom without cron, a
    preset with a different cron, or a cron that isn't Harbor's 6 fields.
    """
    kind = params.get('schedule')
    cron = params.get('cron')
    if kind is None:
        if cron is None:
            return (current['schedule'], current['cron']) if current else ('none', '')
        # A cron on its own is a custom schedule.
        kind = 'custom'
    if kind == 'none':
        if cron:
            raise ValueError('cron can only be set with a schedule other than none.')
        return 'none', ''
    if kind in PRESET_CRON:
        if cron is not None and cron != PRESET_CRON[kind]:
            raise ValueError('schedule %s always runs at %r; use schedule: custom for another cron.'
                             % (kind, PRESET_CRON[kind]))
        return kind, PRESET_CRON[kind]
    if not cron:
        raise ValueError('schedule: custom needs cron.')
    if len(cron.split()) != 6:
        raise ValueError(
            'cron %r has %d fields; Harbor uses 6 (second minute hour day-of-month month day-of-week), '
            'for example "0 0 4 * * 0" for Sundays at 04:00.' % (cron, len(cron.split())))
    return 'custom', cron


def require_known_type(kind):
    """Fail when `kind` is a schedule type the modules can't send back.

    read_schedule() returns whatever type Harbor reports. One outside
    SCHEDULE_TYPES can be shown, and replaced by setting `schedule`, but not
    written again as it is.
    """
    if kind not in API_TYPE:
        raise ValueError('Harbor reports a schedule of type %r, which this module cannot write back. '
                         'Set schedule (one of %s) to replace it.' % (kind, ', '.join(SCHEDULE_TYPES)))


def carried_parameters(current):
    """The stored parameters a write has to send back: every one that has a value.

    Harbor replaces a schedule's parameters as a whole, so one left out is
    lost. That includes parameters the modules have no option for, such as a
    garbage collection's dry_run. The internal ones are already gone
    (parse_parameters).
    """
    return dict((k, v) for k, v in current.items() if v is not None)


def schedule_body(kind, cron, parameters=None):
    """The request body for a schedule write."""
    require_known_type(kind)
    sched = dict(type=API_TYPE[kind])
    if kind != 'none':
        sched['cron'] = cron
    body = dict(schedule=sched)
    if parameters is not None:
        body['parameters'] = parameters
    return body


def schedule_view(timing, parameters, parameter_names):
    """A schedule as the modules return it: timing plus the job's own parameters."""
    view = dict(schedule='none', cron='', next_scheduled_time=None)
    if timing:
        view.update(timing)
    for name in parameter_names:
        view[name] = parameters.get(name)
    return view


def recent_runs(client, path, count):
    """The `count` most recent runs of a job (GC or purge history), newest first.

    More than one page's worth is read page by page. Reading stops at a short
    page, and at a page that brings no run not seen before, so an endpoint
    that ignored `page` could not make this loop or return a run twice.
    """
    if count <= 0:
        return []
    size = min(count, RUNS_PAGE_SIZE)
    runs, seen, page = [], set(), 1
    while len(runs) < count:
        items, dummy = client.request('GET', path, params=dict(page=page, page_size=size, sort='-creation_time'),
                                      expected=(200,), retry=True)
        items = items or []
        fresh = [item for item in items if item.get('id') is None or item.get('id') not in seen]
        seen.update(item.get('id') for item in fresh)
        runs.extend(fresh)
        if len(items) < size or not fresh:
            break
        page += 1
    return [dict(id=item.get('id'), status=item.get('job_status'), trigger=item.get('job_kind'),
                 parameters=parse_parameters(item.get('job_parameters')),
                 creation_time=item.get('creation_time'), update_time=item.get('update_time'))
            for item in runs[:count]]


def comparable(view):
    """The fields that decide whether a schedule has to change."""
    return dict((k, v) for k, v in view.items() if k != 'next_scheduled_time')
