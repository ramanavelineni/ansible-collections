#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: user
short_description: Manage Semaphore UI users
version_added: 0.1.0
description:
  - Creates, updates or deletes a Semaphore UI user, found by its login name. Needs an admin login.
  - The managed user's login name and password are O(login) and O(user_password), because
    O(username) and O(password) are the credentials the module itself logs in with.
  - Only the options you set are compared and changed; the others keep their current value.
  - Semaphore never returns a password, so a changed password cannot be detected. By default a
    declared password is sent on every run and the task reports C(changed); see O(update_secret).
  - The module never changes or deletes the user it logs in as.
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
  login:
    description:
      - Login name (username) of the managed user. Users are looked up by it; renaming is not supported.
    type: str
    required: true
  state:
    description:
      - V(present) creates the user or updates it to match.
      - V(absent) deletes it.
    type: str
    choices: [present, absent]
    default: present
  name:
    description:
      - Display name. Required to create a user.
    type: str
  email:
    description:
      - Email address. Required to create a user.
    type: str
  admin:
    description:
      - Whether the user is a Semaphore administrator. Defaults to V(false) for a new user.
    type: bool
  alert:
    description:
      - Whether the user receives alert emails. Defaults to V(false) for a new user.
    type: bool
  external:
    description:
      - Whether the user signs in through an external provider (LDAP or OIDC) and has no local
        password. Only set when the user is created; Semaphore cannot change it afterwards.
      - Defaults to V(false) for a new user.
    type: bool
  user_password:
    description:
      - The managed user's password. Required to create a user that is not O(external); not allowed
        for an external user.
      - For an existing user, leave it out to keep the stored password.
    type: str
  update_secret:
    description:
      - V(always) sends the declared O(user_password) on every run, so the task always reports C(changed)
        when a password is declared. The stored password then always matches what you declare.
      - V(on_create) sets it only when the user is created; later runs leave it alone.
    type: str
    choices: [always, on_create]
    default: always
notes:
  - For the user the module logs in as, any change or deletion fails; a declared password is left
    alone with a warning.
  - Semaphore 2.18 cannot delete a user who has ever logged in (it answers HTTP 500); the module
    fails with an explanation. Semaphore 2.19 deletes such users.
seealso:
  - module: ramanavelineni.semaphoreui.user_info
    description: Reads users without changing them.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Operator account
  ramanavelineni.semaphoreui.user:
    url: https://semaphore.example.com
    username: admin
    password: "{{ semaphore_admin_password }}"
    login: ops
    name: Ops
    email: ops@example.com
    user_password: "{{ vault_ops_password }}"

- name: OIDC user without a local password
  ramanavelineni.semaphoreui.user:
    login: alice
    name: Alice
    email: alice@example.com
    external: true
'''

RETURN = r'''
user:
  description:
    - The user after the change, or as it would be in check mode. Never contains a password.
    - Empty after a deletion.
  returned: always
  type: dict
  contains:
    id:
      description: User id.
      type: int
    username:
      description: Login name.
      type: str
    name:
      description: Display name.
      type: str
    email:
      description: Email address.
      type: str
    admin:
      description: Whether the user is a Semaphore administrator.
      type: bool
    alert:
      description: Whether the user receives alert emails.
      type: bool
    external:
      description: Whether the user signs in through an external provider and has no local password.
      type: bool
  sample:
    id: 3
    username: ops
    name: Ops
    email: ops@example.com
    admin: false
    alert: false
    external: false
password_updated:
  description: Whether the module sent the user's password.
  returned: always
  type: bool
  sample: true
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    SemaphoreError,
    diff_fields,
    find_by_name,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
    server_minor,
    user_view,
)

MANAGED = ('name', 'email', 'admin', 'alert')


def validate(params):
    # Not in the argument spec: it depends on the value of external, and
    # mutually_exclusive would also refuse external: false with a password.
    if params['state'] == 'present' and params['external'] and params['user_password'] is not None:
        raise ValueError('An external user has no local password; drop user_password or external.')


def ensure(module, client):
    params = module.params
    validate(params)
    client.warn_if_untested()

    me = client.get('/user') or {}
    users = client.list('/users')
    current = find_by_name(users, params['login'], 'user', field='username')
    if params['state'] == 'present' and params['email']:
        # Emails are unique; Semaphore answers a clash with a bare 400.
        taken = [u.get('username') for u in users
                 if u.get('email') == params['email'] and u.get('username') != params['login']]
        if taken:
            raise ValueError('Email %r already belongs to user %r; each user needs its own email.'
                             % (params['email'], taken[0]))
    before = user_view(current) if current else {}
    result = dict(changed=False, user=before, password_updated=False)
    is_me = bool(current) and current.get('id') == me.get('id')

    if params['state'] == 'absent':
        if not current:
            result.update(diff=dict(before={}, after={}))
            return result
        if is_me:
            raise ValueError('Refusing to delete %r: it is the user this module logs in as.' % params['login'])
        if not module.check_mode:
            try:
                client.delete('/users/%d' % current['id'])
            except SemaphoreError as e:
                minor = server_minor(client.info().get('version'))
                if e.status != 500 or (minor is not None and minor >= (2, 19)):
                    raise
                # Before 2.19 the session table has no ON DELETE CASCADE, so
                # a user with any login session cannot be deleted; the server
                # only answers a bare 500.
                raise ValueError(
                    'Semaphore refused to delete user %r (HTTP 500). Semaphore before 2.19 cannot delete a '
                    'user who has ever logged in: their login sessions still refer to the user. Upgrade to '
                    '2.19, or remove the user\'s sessions from the database. (%s)' % (params['login'], e.message()))
        result.update(changed=True, user={}, diff=dict(before=before, after={}))
        return result

    if not current:
        missing = [o for o in ('name', 'email') if not params[o]]
        if not params['external'] and params['user_password'] is None:
            missing.append('user_password')
        if missing:
            raise ValueError('Creating user %r needs %s.' % (params['login'], ', '.join(missing)))
        body = dict(username=params['login'], name=params['name'], email=params['email'],
                    admin=bool(params['admin']), alert=bool(params['alert']), external=bool(params['external']))
        if not params['external']:
            body['password'] = params['user_password']
        after = user_view(body)
        after.pop('id')
        if not module.check_mode:
            after = user_view(client.post('/users', body))
        result.update(changed=True, user=after, password_updated=not params['external'],
                      diff=dict(before={}, after=after))
        return result

    if params['external'] is not None and params['external'] != before['external']:
        raise ValueError(
            'User %r is %san external user; Semaphore cannot change that after creation. Delete the user '
            'and create it again.' % (params['login'], '' if before['external'] else 'not '))
    if before['external'] and params['user_password'] is not None:
        raise ValueError('User %r is an external user and has no local password; drop user_password.' % params['login'])

    desired = dict((k, params[k]) for k in MANAGED)
    changed = diff_fields(desired, before)
    send_password = params['user_password'] is not None and params['update_secret'] == 'always'
    if is_me:
        if changed:
            raise ValueError('Refusing to change %s of %r: it is the user this module logs in as.'
                             % (', '.join(changed), params['login']))
        if send_password:
            module.warn('Password of %r not sent: it is the user this module logs in as.' % params['login'])
        result.update(diff=dict(before=before, after=before))
        return result

    after = dict(before)
    after.update((k, desired[k]) for k in changed)
    if not module.check_mode:
        if changed:
            # The update rewrites name, username, email, alert, admin and pro
            # together, so the current values of the others go back as they are.
            body = dict(current)
            body.update((k, after[k]) for k in MANAGED)
            body.pop('password', None)
            client.put('/users/%d' % current['id'], body)
        if send_password:
            # An admin setting another user's password needs no current password.
            client.post('/users/%d/password' % current['id'], dict(password=params['user_password']), expected=(204,))
    result.update(changed=bool(changed) or send_password, user=after, password_updated=send_password,
                  diff=dict(before=before, after=after))
    return result


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        login=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        name=dict(type='str'),
        email=dict(type='str'),
        admin=dict(type='bool'),
        alert=dict(type='bool'),
        external=dict(type='bool'),
        user_password=dict(type='str', no_log=True),
        update_secret=dict(type='str', default='always', choices=['always', 'on_create'], no_log=False),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True, **semaphore_module_kwargs())
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
