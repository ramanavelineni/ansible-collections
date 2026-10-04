# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Tasks (runs of a template) as the task and task_info modules read them."""

import json
import time

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import SemaphoreError

# A task in one of these is over. Every other status still changes by itself,
# except waiting_confirmation, which waits for a person.
FINAL_STATUSES = ('success', 'error', 'stopped')
NEEDS_CONFIRMATION = 'waiting_confirmation'

# Semaphore answers at most this many tasks for one list.
LIST_LIMIT = 200

# The last lines of a task's output are stored a moment after its final status
# (seen up to 0.3 s later on 2.18 and 2.19). The output of a finished task is
# read again after this many seconds until two reads agree, at most this often.
OUTPUT_SETTLE = 0.5
OUTPUT_READS = 4


def template_names(templates):
    """Template id -> name, from a project's template list."""
    return dict((tpl.get('id'), tpl.get('name')) for tpl in templates)


def _json_field(text, empty):
    """A field Semaphore stores as a JSON string, parsed. `empty` when unset; the text itself when it isn't JSON."""
    if not text:
        return empty
    try:
        value = json.loads(text)
    except ValueError:
        return text
    return value if isinstance(value, type(empty)) else text


def task_view(task, project, names, output=None):
    """A task as task and task_info return it.

    The API leaves out what is empty; every key is filled in here so that
    results have one shape. `secret` (the values of secret survey variables)
    is never part of it: Semaphore does not store it either.
    """
    status = task.get('status') or ''
    return dict(
        id=task.get('id'),
        project=project,
        template=names.get(task.get('template_id')),
        template_id=task.get('template_id'),
        status=status,
        finished=status in FINAL_STATUSES,
        message=task.get('message') or '',
        playbook=task.get('playbook') or '',
        git_branch=task.get('git_branch') or '',
        arguments=_json_field(task.get('arguments'), []),
        variables=_json_field(task.get('environment'), {}),
        task_params=dict(task.get('params') or {}),
        inventory_id=task.get('inventory_id'),
        version=task.get('version') or '',
        build_task_id=task.get('build_task_id'),
        commit_hash=task.get('commit_hash') or '',
        commit_message=task.get('commit_message') or '',
        user_id=task.get('user_id'),
        created=task.get('created') or '',
        start=task.get('start') or '',
        end=task.get('end') or '',
        output=list(output or []),
    )


def get_task(client, base, task_id):
    """The task with this id in the project at `base`, or None.

    Semaphore answers 400 for a task id the project doesn't have (404 is
    taken as the same, should a version answer that).
    """
    try:
        return client.get('%s/tasks/%d' % (base, task_id))
    except SemaphoreError as e:
        if e.status in (400, 404):
            return None
        raise


def read_output(client, base, task_id, lines):
    """The task's output, one entry per line Semaphore stored, oldest first.

    `lines` is how many of the last lines to return: 0 reads nothing, a
    negative number returns them all.
    """
    if lines == 0:
        return []
    entries = client.get('%s/tasks/%d/output' % (base, task_id)) or []
    out = [(entry.get('output') or '').rstrip('\n') for entry in entries]
    return out if lines < 0 else out[-lines:]


def settled_output(client, base, task_id, lines):
    """read_output() of a finished task, read again until it stops growing."""
    if lines == 0:
        return []
    count, entries = None, []
    for dummy in range(OUTPUT_READS):
        entries = client.get('%s/tasks/%d/output' % (base, task_id)) or []
        if count is not None and len(entries) == count:
            break
        count = len(entries)
        time.sleep(OUTPUT_SETTLE)
    out = [(entry.get('output') or '').rstrip('\n') for entry in entries]
    return out if lines < 0 else out[-lines:]


def wait_for_end(client, base, task, interval, timeout):
    """(task, ended) after polling until the task is over, wants a confirmation, or `timeout` seconds went by.

    Time is counted in the waits between two reads, so a slow server makes the
    wait longer than `timeout`, never shorter. `ended` is False when the wait
    gave up.
    """
    waited = 0
    while True:
        status = task.get('status')
        if status in FINAL_STATUSES or status == NEEDS_CONFIRMATION:
            return task, status in FINAL_STATUSES
        if waited >= timeout:
            return task, False
        time.sleep(interval)
        waited += interval
        task = client.get('%s/tasks/%d' % (base, task['id'])) or task
