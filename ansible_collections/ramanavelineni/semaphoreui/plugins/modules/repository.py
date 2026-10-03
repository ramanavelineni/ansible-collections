#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: repository
short_description: Manage repositories in a Semaphore UI project
version_added: 0.1.0
description:
  - Creates, updates or deletes a repository (the Git repository or local path templates run
    from) in a project, found by its name.
  - Only the options you set are compared and changed; the others keep their current value.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
options:
  project:
    description:
      - Name of the project the repository belongs to.
    type: str
    required: true
  name:
    description:
      - Name of the repository. Repositories are looked up by this name within the project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the repository or updates it to match.
      - V(absent) deletes it. It fails, listing them, while templates or other objects still use
        the repository.
    type: str
    choices: [present, absent]
    default: present
  git_url:
    description:
      - Where to clone from, for example C(git@github.com:example/ansible.git) or
        C(https://github.com/example/ansible.git), or an absolute path on the Semaphore server.
      - Required to create the repository.
      - Changing it makes Semaphore delete the repository's existing checkouts.
    type: str
  git_branch:
    description:
      - Branch to check out.
      - Required to create the repository, unless O(git_url) is a local path.
    type: str
  ssh_key:
    description:
      - Name of the key in the project's Key Store used to clone.
      - Use a key of type V(none) (every project has one named C(None)) for a public repository.
      - Required to create the repository.
    type: str
'''

EXAMPLES = r'''
- name: Repository cloned over SSH
  ramanavelineni.semaphoreui.repository:
    project: homelab
    name: ansible
    git_url: git@github.com:example/ansible.git
    git_branch: main
    ssh_key: github-deploy

- name: Public repository
  ramanavelineni.semaphoreui.repository:
    project: homelab
    name: examples
    git_url: https://github.com/example/examples.git
    git_branch: main
    ssh_key: None
'''

RETURN = r'''
repository:
  description:
    - The repository after the change, or as it would be in check mode.
    - Empty after a deletion.
  returned: always
  type: dict
  contains:
    id:
      description: Repository id. Absent when a repository would be created in check mode.
      type: int
      returned: when the repository exists
    name:
      description: Repository name.
      type: str
    git_url:
      description: Clone URL or local path.
      type: str
    git_branch:
      description: Branch.
      type: str
    ssh_key:
      description: Name of the key used to clone.
      type: str
    ssh_key_id:
      description: Id of that key.
      type: int
    project_id:
      description: Id of the project.
      type: int
  sample:
    id: 1
    name: ansible
    git_url: git@github.com:example/ansible.git
    git_branch: main
    ssh_key: github-deploy
    ssh_key_id: 4
    project_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    diff_fields,
    find_by_name,
    refuse_delete_if_used,
    resolve_project,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def is_local_path(url):
    # The same rule Semaphore uses for a local repository: an absolute path
    # needs no branch. (Windows drive paths are left to the server to judge.)
    return url.startswith('/')


def normalize(repo, key_names):
    return dict(
        id=repo.get('id'),
        name=repo.get('name'),
        git_url=repo.get('git_url') or '',
        git_branch=repo.get('git_branch') or '',
        ssh_key_id=repo.get('ssh_key_id'),
        ssh_key=key_names.get(repo.get('ssh_key_id')),
        project_id=repo.get('project_id'),
    )


def ensure(module, client):
    params = module.params
    client.warn_if_untested()

    project_id = resolve_project(client, params['project'], missing_ok=params['state'] == 'absent')
    if project_id is None:
        # The project is gone, and everything in it went with it.
        return dict(changed=False, repository={}, diff=dict(before={}, after={}))
    base = '/project/%d' % project_id
    current = find_by_name(client.list(base + '/repositories'), params['name'], 'repository')

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, repository={}, diff=dict(before={}, after={}))
        before = normalize(current, {})
        refuse_delete_if_used(client, '%s/repositories/%d' % (base, current['id']), 'repository', params['name'])
        if not module.check_mode:
            client.delete('%s/repositories/%d' % (base, current['id']))
        return dict(changed=True, repository={}, diff=dict(before=before, after={}))

    keys = client.list(base + '/keys')
    key_names = dict((k['id'], k['name']) for k in keys)
    ssh_key_id = None
    if params['ssh_key'] is not None:
        key = find_by_name(keys, params['ssh_key'], 'key')
        if key is None:
            raise ValueError('Key %r does not exist in project %r.' % (params['ssh_key'], params['project']))
        ssh_key_id = key['id']

    if not current:
        missing = [o for o in ('git_url', 'ssh_key') if params[o] is None]
        if params['git_url'] is not None and not is_local_path(params['git_url']) and not params['git_branch']:
            missing.append('git_branch')
        if missing:
            raise ValueError('Creating repository %r needs %s.' % (params['name'], ', '.join(missing)))
        body = dict(project_id=project_id, name=params['name'], git_url=params['git_url'],
                    git_branch=params['git_branch'] or '', ssh_key_id=ssh_key_id)
        after = normalize(body, key_names)
        after.pop('id')
        if not module.check_mode:
            after = normalize(client.post(base + '/repositories', body), key_names)
        return dict(changed=True, repository=after, diff=dict(before={}, after=after))

    before = normalize(current, key_names)
    desired = dict(git_url=params['git_url'], git_branch=params['git_branch'], ssh_key_id=ssh_key_id)
    changed = diff_fields(desired, before)
    if not changed:
        return dict(changed=False, repository=before, diff=dict(before=before, after=before))

    after = dict(before)
    after.update((k, desired[k]) for k in changed)
    after['ssh_key'] = key_names.get(after['ssh_key_id'])
    if not module.check_mode:
        # The update writes name, git_url, git_branch and ssh_key_id together
        # and rejects a body whose id or project_id differ from the URL's.
        client.put('%s/repositories/%d' % (base, current['id']), dict(
            id=current['id'], project_id=project_id, name=params['name'],
            git_url=after['git_url'], git_branch=after['git_branch'], ssh_key_id=after['ssh_key_id']))
    return dict(changed=True, repository=after, diff=dict(before=before, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        git_url=dict(type='str'),
        git_branch=dict(type='str'),
        ssh_key=dict(type='str', no_log=False),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs()
    )
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
