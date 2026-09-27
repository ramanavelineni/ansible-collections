#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: key_store
short_description: Manage keys in a Semaphore UI project's Key Store
version_added: 0.1.0
description:
  - Creates, updates or deletes a key (SSH key, login and password, or none) in a project's
    Key Store, found by its name.
  - Semaphore never returns a key's secret, so a changed secret cannot be detected. By default
    a declared secret is sent on every run and the task reports C(changed); see O(update_secret).
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
      - Name of the project the key belongs to.
    type: str
    required: true
  name:
    description:
      - Name of the key. Keys are looked up by this name within the project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the key or updates it to match.
      - V(absent) deletes it. It fails, listing them, while templates, inventories, repositories or
        other objects still use the key.
    type: str
    choices: [present, absent]
    default: present
  type:
    description:
      - Kind of key. Required with O(state=present).
      - V(ssh) is a private key, V(login_password) a login and password (also used for
        ansible-vault passwords and become passwords), V(none) a key with no secret.
      - When an existing key has another type, it is changed in place. Changing to V(ssh) or
        V(login_password) needs the matching secret option.
    type: str
    choices: [ssh, login_password, none]
  ssh:
    description:
      - The SSH key, for O(type=ssh).
    type: dict
    suboptions:
      login:
        description: User name to connect as.
        type: str
        default: ''
      passphrase:
        description: Passphrase of the private key, if it has one.
        type: str
        default: ''
      private_key:
        description:
          - The private key.
          - Required to create the key. For an existing key, leave it out to keep the stored secret.
        type: str
  login_password:
    description:
      - The login and password, for O(type=login_password).
    type: dict
    suboptions:
      login:
        description: Login name. Leave empty for an ansible-vault or become password.
        type: str
        default: ''
      password:
        description:
          - The password.
          - Required to create the key. For an existing key, leave it out to keep the stored secret.
        type: str
  update_secret:
    description:
      - V(always) sends the declared secret on every run, so the task always reports C(changed)
        for a key with a secret. The stored secret then always matches what you declare.
      - V(on_create) sends it only when the key is created or its type changes; later runs leave
        the stored secret alone and report C(ok).
    type: str
    choices: [always, on_create]
    default: always
  force_repository_key_update:
    description:
      - Allow updating a key that one of the project's repositories uses.
      - B(Every update of such a key makes Semaphore delete all checkouts of those repositories.)
        A task running from one of them at that moment fails. Without this option the module
        leaves such a key's secret alone and warns, and fails if the key's type has to change.
    type: bool
    default: false
notes:
  - Semaphore creates a key named C(None) of type V(none) in every new project.
  - The O(ssh.login) and O(login_password.login) values travel with the secret and are not
    returned by the API, so they are only compared and sent together with the secret.
'''

EXAMPLES = r'''
- name: Deploy key for Git over SSH
  ramanavelineni.semaphoreui.key_store:
    project: homelab
    name: github-deploy
    type: ssh
    ssh:
      login: git
      private_key: "{{ vault_github_deploy_key }}"

- name: Vault password, set once and left alone afterwards
  ramanavelineni.semaphoreui.key_store:
    project: homelab
    name: ansible-vault
    type: login_password
    login_password:
      password: "{{ vault_ansible_vault_password }}"
    update_secret: on_create

- name: Rotate a key a repository uses (run from outside Semaphore)
  ramanavelineni.semaphoreui.key_store:
    project: homelab
    name: github-deploy
    type: ssh
    ssh:
      login: git
      private_key: "{{ vault_github_deploy_key_new }}"
    force_repository_key_update: true
'''

RETURN = r'''
key:
  description:
    - The key after the change, or as it would be in check mode. Never contains a secret.
    - Empty after a deletion.
  returned: always
  type: dict
  contains:
    id:
      description: Key id. Absent when a key would be created in check mode.
      type: int
      returned: when the key exists
    name:
      description: Key name.
      type: str
    type:
      description: Key type.
      type: str
    project_id:
      description: Id of the project.
      type: int
  sample:
    id: 4
    name: github-deploy
    type: ssh
    project_id: 1
secret_updated:
  description: Whether the module sent the key's secret.
  returned: always
  type: bool
repositories:
  description: Names of the project's repositories that use this key.
  returned: always
  type: list
  elements: str
  sample: [ansible]
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    find_by_name,
    refuse_delete_if_used,
    resolve_project,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)

SECRET_OPTION = dict(ssh=('ssh', 'private_key'), login_password=('login_password', 'password'))


def normalize(key, project_id):
    return dict(id=key.get('id'), name=key.get('name'), type=key.get('type'), project_id=project_id)


def secret_payload(params):
    """The key's type-specific block for a request body, or {} for none."""
    key_type = params['type']
    if key_type == 'ssh':
        ssh = params['ssh']
        return dict(ssh=dict(login=ssh['login'], passphrase=ssh['passphrase'], private_key=ssh['private_key']))
    if key_type == 'login_password':
        lp = params['login_password']
        return dict(login_password=dict(login=lp['login'], password=lp['password']))
    return {}


def secret_given(params):
    option = SECRET_OPTION.get(params['type'])
    if option is None:
        return False
    block = params[option[0]] or {}
    return block.get(option[1]) is not None


def validate(params):
    if params['state'] != 'present':
        return
    if params['type'] is None:
        raise ValueError('type is required when state is present.')
    for key_type, (option, dummy) in SECRET_OPTION.items():
        if params[option] is not None and params['type'] != key_type:
            raise ValueError('%s is only valid with type: %s.' % (option, key_type))


def ensure(module, client):
    params = module.params
    validate(params)
    client.warn_if_untested()

    project_id = resolve_project(client, params['project'])
    base = '/project/%d' % project_id
    current = find_by_name(client.list(base + '/keys'), params['name'], 'key')
    before = normalize(current, project_id) if current else {}

    repositories = []
    if current:
        repositories = sorted(r['name'] for r in client.list(base + '/repositories')
                              if r.get('ssh_key_id') == current['id'])
    result = dict(changed=False, key=before, secret_updated=False, repositories=repositories)

    if params['state'] == 'absent':
        if not current:
            result.update(diff=dict(before={}, after={}))
            return result
        refuse_delete_if_used(client, '%s/keys/%d' % (base, current['id']), 'key', params['name'])
        if not module.check_mode:
            client.delete('%s/keys/%d' % (base, current['id']))
        result.update(changed=True, key={}, diff=dict(before=before, after={}))
        return result

    if not current:
        if params['type'] != 'none' and not secret_given(params):
            raise ValueError('Creating a %s key needs its secret (%s.%s).'
                             % ((params['type'],) + SECRET_OPTION[params['type']]))
        after = dict(name=params['name'], type=params['type'], project_id=project_id)
        if not module.check_mode:
            body = dict(project_id=project_id, name=params['name'], type=params['type'])
            body.update(secret_payload(params))
            after = normalize(client.post(base + '/keys', body), project_id)
        result.update(changed=True, key=after, secret_updated=params['type'] != 'none',
                      diff=dict(before={}, after=after))
        return result

    type_changed = current.get('type') != params['type']
    if type_changed and params['type'] != 'none' and not secret_given(params):
        raise ValueError(
            'Key %r is of type %s; changing it to %s needs the secret (%s.%s).'
            % ((params['name'], current.get('type'), params['type']) + SECRET_OPTION[params['type']]))
    send = type_changed or (secret_given(params) and params['update_secret'] == 'always')
    if not send:
        result.update(diff=dict(before=before, after=before))
        return result

    if repositories and not params['force_repository_key_update']:
        if type_changed:
            raise ValueError(
                'Key %r must change from %s to %s, but repositories %s use it and Semaphore deletes '
                'their checkouts on every update of the key. Set force_repository_key_update: true '
                'to update it anyway, while no task of those repositories is running or queued.'
                % (params['name'], current.get('type'), params['type'], ', '.join(repositories)))
        module.warn(
            'Secret of key %r not sent: repositories %s use it, and Semaphore deletes their checkouts '
            'on every update of the key. Set force_repository_key_update: true to rotate it, while no '
            'task of those repositories is running or queued.' % (params['name'], ', '.join(repositories)))
        result.update(diff=dict(before=before, after=before))
        return result

    after = dict(before, type=params['type'])
    if not module.check_mode:
        # override_secret makes the server write type and secret; without it
        # only the name changes and the secret is silently ignored. The body
        # needs id and project_id: the handler rejects a mismatch or a missing
        # project_id.
        body = dict(id=current['id'], project_id=project_id, name=params['name'],
                    type=params['type'], override_secret=True)
        body.update(secret_payload(params))
        client.put('%s/keys/%d' % (base, current['id']), body)
    result.update(changed=True, key=after, secret_updated=params['type'] != 'none',
                  diff=dict(before=before, after=after))
    return result


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        type=dict(type='str', choices=['ssh', 'login_password', 'none']),
        ssh=dict(type='dict', options=dict(
            login=dict(type='str', default=''),
            passphrase=dict(type='str', default='', no_log=True),
            private_key=dict(type='str', no_log=True),
        )),
        login_password=dict(type='dict', no_log=False, options=dict(
            login=dict(type='str', default=''),
            password=dict(type='str', no_log=True),
        )),
        update_secret=dict(type='str', default='always', choices=['always', 'on_create'], no_log=False),
        force_repository_key_update=dict(type='bool', default=False),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs()
    )
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
