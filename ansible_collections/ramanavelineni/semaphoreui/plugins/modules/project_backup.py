#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: project_backup
short_description: Read a Semaphore UI project's backup, and write it to a file
version_added: 0.4.0
description:
  - Reads the backup Semaphore makes of a project, the same document as B(Backup) in the project's settings, and
    returns it. With O(dest) it is also written to a file.
  - A backup describes the project's keys, repositories, inventories, variable groups, views, templates,
    schedules and integrations, and names what they refer to instead of using ids. It holds no task history
    and no team members.
  - B(A backup holds no secrets.) Semaphore writes a key as its name and type only, and leaves out the values
    of secret variables. A project restored from it has keys that are empty. See
    M(ramanavelineni.semaphoreui.project_restore).
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
attributes:
  check_mode:
    support: full
    details:
      - The backup is read and returned; the file at O(dest) is not written.
  diff_mode:
    support: full
    details:
      - With O(dest), the diff is between what the file holds and the backup.
options:
  project:
    description:
      - Name of the project.
      - Mutually exclusive with O(project_id); one of the two is required.
    type: str
  project_id:
    description:
      - Id of the project, as an alternative to O(project).
      - With it the list of projects is not read, so a project is found on a server with 200 or more
        projects too. Semaphore cuts that list off at 200, and O(project) fails there.
      - Mutually exclusive with O(project). One of the two is required.
    type: int
  dest:
    description:
      - File to write the backup to, as JSON, on the host the module runs on. Its directory must exist.
      - The file is replaced in one step, and only when what it holds differs from the backup. How the JSON
        is laid out does not count as a difference.
      - Without it the module only returns the backup and never reports a change.
    type: path
  mode:
    description:
      - Permissions of the file at O(dest), as an octal number in quotes.
      - A backup holds no secrets, but it does describe the whole project; the default keeps it to the owner.
    type: str
    default: "0600"
notes:
  - The format of a backup belongs to the Semaphore version that wrote it. A newer version adds sections (2.19
    adds C(workflows)).
seealso:
  - module: ramanavelineni.semaphoreui.project_restore
    description: Creates a project from a backup.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Keep a backup of the homelab project
  ramanavelineni.semaphoreui.project_backup:
    project: homelab
    dest: /var/backups/semaphore/homelab.json

- name: Read the backup without writing a file
  ramanavelineni.semaphoreui.project_backup:
    project: homelab
  register: homelab_backup
'''

RETURN = r'''
backup:
  description:
    - The backup, as Semaphore wrote it. Its sections are C(meta) (the project itself), C(keys),
      C(repositories), C(inventories), C(environments) (variable groups), C(views), C(templates),
      C(schedules), C(integrations), C(integration_aliases), C(secret_storages), C(roles), C(runners) and,
      from Semaphore 2.19, C(workflows).
    - Objects refer to each other by name, and nothing has an id.
  returned: always
  type: dict
  sample:
    meta:
      name: homelab
      alert: false
      max_parallel_tasks: 0
      type: ""
    repositories:
      - name: ansible
        git_url: git@github.com:example/ansible.git
        git_branch: main
        ssh_key: deploy
file:
  description: The file the backup is in, which is O(dest). Empty without O(dest).
  returned: always
  type: str
  sample: /var/backups/semaphore/homelab.json
'''

import json
import os
import re
import tempfile

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def file_mode(text):
    if not re.match(r'^[0-7]{3,4}$', text):
        raise ValueError('mode must be an octal number such as "0600". Got %r.' % text)
    return int(text, 8)


def stored(dest):
    """(what the file holds as parsed JSON or None, its permissions or None)."""
    try:
        permissions = os.stat(dest).st_mode & 0o7777
    except OSError:
        return None, None
    try:
        with open(dest, encoding='utf-8') as f:
            return json.load(f), permissions
    except (OSError, ValueError):
        return None, permissions


def write(dest, backup, mode):
    """Put the backup at dest in one step: a reader sees the old file or the new one, never half of it."""
    directory = os.path.dirname(os.path.abspath(dest))
    if not os.path.isdir(directory):
        raise ValueError('The directory of dest, %r, does not exist on the host this module runs on.' % directory)
    fd, tmp = tempfile.mkstemp(prefix='.semaphore-backup-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(backup, f, indent=2, sort_keys=True)
            f.write('\n')
        os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_backup(module, client):
    params = module.params
    client.warn_if_untested()
    mode = file_mode(params['mode'])
    project_id = project_ref(client, params)[0]
    backup = client.get('/project/%d/backup' % project_id)
    if not isinstance(backup, dict):
        raise ValueError('GET %s/api/project/%d/backup did not return a backup.' % (client.url, project_id))

    dest = params['dest']
    if not dest:
        return dict(changed=False, backup=backup, file='', diff=dict(before={}, after={}))
    if os.path.isdir(dest):
        raise ValueError('dest %r is a directory. Name the file to write.' % dest)

    before, permissions = stored(dest)
    content_changed = before != backup
    if not module.check_mode:
        try:
            if content_changed:
                write(dest, backup, mode)
            elif permissions != mode:
                os.chmod(dest, mode)
        except OSError as e:
            raise ValueError('Cannot write dest %r on the host this module runs on: %s' % (dest, e))
    # Not under "dest": Ansible adds a file's owner, size and more to a result that has that key.
    return dict(changed=content_changed or permissions != mode, backup=backup, file=dest,
                diff=dict(before=before if before is not None else {}, after=backup))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str'),
        project_id=dict(type='int'),
        dest=dict(type='path'),
        mode=dict(type='str', default='0600'),
    )
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: read_backup(module, client))


if __name__ == '__main__':
    main()
