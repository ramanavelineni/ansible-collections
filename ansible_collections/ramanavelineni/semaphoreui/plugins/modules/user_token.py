#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: user_token
short_description: Manage the API tokens of the user that logs in
version_added: 0.4.0
description:
  - Creates or revokes an API token of the user the module logs in as, found by its name. Semaphore has no
    way to manage another user's tokens, not even for an administrator.
  - B(The token is returned once), as RV(token), by the task that creates it. Semaphore never shows it again,
    because its list of tokens holds only the first eight characters of each. A later run finds the token by
    its name, changes nothing and returns no token.
  - A token that has expired, or was revoked, is replaced by a new one of the same name.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
attributes:
  check_mode:
    support: full
    details:
      - No token is created, so RV(token) is empty.
  diff_mode:
    support: full
    details:
      - The token itself is in no diff.
options:
  name:
    description:
      - Name of the token. Tokens are looked up by this name among the tokens of the user that logs in.
      - Semaphore lets several tokens have the same name. With O(state=present) the module fails when it
        finds more than one that is still valid; O(state=absent) revokes them all.
    type: str
    required: true
  state:
    description:
      - V(present) creates the token if no valid token of that name exists.
      - V(absent) revokes every token of that name.
    type: str
    choices: [present, absent]
    default: present
  expires_at:
    description:
      - When the token stops working, as an ISO 8601 time with a time zone, for example
        V(2027-01-01T00:00:00Z). Without it the token does not expire.
      - Only used when the token is created. Semaphore cannot change the expiry of a token; when a valid
        token of that name has another expiry, the module fails and says so.
    type: str
notes:
  - The token is returned in the task result. Set C(no_log) on the task so it is not shown in the output.
  - Revoking the token the task itself connects with (O(api_token)) is refused. Connect with O(username) and
    O(password), or with another token.
seealso:
  - module: ramanavelineni.semaphoreui.user
    description: Manages users.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: A token for the configuration playbook
  ramanavelineni.semaphoreui.user_token:
    name: semaphore-config
  register: config_token
  no_log: true

- name: Store it where the playbook reads it (only the run that created it has it)
  ansible.builtin.copy:
    content: "{{ config_token.token }}"
    dest: /etc/semaphore-config/api_token
    mode: "0600"
  when: config_token.token
  no_log: true

- name: A token that stops working at the end of the year
  ramanavelineni.semaphoreui.user_token:
    name: migration
    expires_at: "2026-12-31T23:59:59Z"
  register: migration_token
  no_log: true

- name: Revoke it
  ramanavelineni.semaphoreui.user_token:
    name: migration
    state: absent
'''

RETURN = r'''
user_token:
  description:
    - The token's entry after the change, or as it would be in check mode. It never holds the token itself.
    - Empty after a revocation.
  returned: always
  type: dict
  contains:
    id:
      description:
        - The first eight characters of the token, which is all Semaphore lists of it. Absent when a token
          would be created in check mode.
      type: str
      returned: when the token exists
    name:
      description: Name of the token.
      type: str
    created:
      description: When the token was created. Absent when a token would be created in check mode.
      type: str
      returned: when the token exists
    expires_at:
      description: When the token stops working, in UTC. Null for a token that does not expire.
      type: str
    expired:
      description: Whether the token no longer works, because it was revoked or its time has passed.
      type: bool
  sample:
    id: ajs1r2wq
    name: semaphore-config
    created: "2026-10-04T15:52:58Z"
    expires_at: null
    expired: false
token:
  description:
    - The API token, for O(api_token) or a Bearer authorization header.
    - Empty unless this task created the token (and not in check mode).
  returned: always
  type: str
  sample: "<the token>"
'''

from datetime import datetime, timezone

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    find_by_name,
    normalize_time,
    parse_time,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)

# What Semaphore lists of a token, and what it finds a token by when asked to delete it.
PREFIX = 8


def is_over(moment, now):
    """Whether an ISO time, as the server or the task wrote it, is not after now."""
    parsed = parse_time(moment)
    if parsed is None:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= now


def view(token, now):
    expires_at = normalize_time(token.get('expires_at'))
    return dict(
        id=(token.get('id') or '')[:PREFIX],
        name=token.get('name') or '',
        created=normalize_time(token.get('created')),
        expires_at=expires_at,
        expired=bool(token.get('expired', False)) or bool(expires_at and is_over(expires_at, now)),
    )


def wanted_expiry(params, now):
    """expires_at as the server gets it, or None. Fails on what Semaphore would refuse with an empty answer."""
    if params['expires_at'] is None:
        return None
    moment = parse_time(params['expires_at'])
    if moment is None or moment.tzinfo is None:
        raise ValueError('expires_at %r is not a date and time with a time zone. Write it like '
                         '2027-01-01T00:00:00Z or 2027-01-01T02:00:00+02:00.' % params['expires_at'])
    if moment <= now:
        raise ValueError('expires_at %r is in the past; Semaphore only creates a token that still works.'
                         % params['expires_at'])
    return normalize_time(params['expires_at'])


def revoke(module, client, token):
    # Semaphore deletes by the start of a token, and the list has no more than this of it.
    prefix = token['id'][:PREFIX]
    if client.api_token and client.api_token[:PREFIX] == prefix:
        raise ValueError('Token %r is the one this task connects with (api_token). Revoking it would cut the '
                         'task off; connect with username and password, or with another token.' % token.get('name'))
    if not module.check_mode:
        client.delete('/user/tokens/%s' % prefix)


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    now = datetime.now(timezone.utc)
    name = params['name']
    if not name.strip():
        raise ValueError('name must not be empty: the token is found by it.')
    expiry = wanted_expiry(params, now) if params['state'] == 'present' else None

    tokens = client.list('/user/tokens')
    for token in tokens:
        if 'name' not in token:
            raise ValueError('This Semaphore server stores no names for API tokens, so a token cannot be found '
                             'by its name and this module cannot manage tokens on it.')
    named = [t for t in tokens if t.get('name') == name]
    result = dict(changed=False, user_token={}, token='')

    if params['state'] == 'absent':
        if not named:
            result.update(diff=dict(before={}, after={}))
            return result
        for token in named:
            revoke(module, client, token)
        result.update(changed=True, diff=dict(before=view(named[0], now), after={}))
        return result

    valid = [t for t in named if not view(t, now)['expired']]
    current = find_by_name(valid, name, 'API token')
    if current:
        before = view(current, now)
        if expiry is not None and before['expires_at'] != expiry:
            raise ValueError(
                'Token %r exists and %s; the task asks for %s. Semaphore cannot change the expiry of a token. '
                'Revoke it with state: absent and create it again; that gives it a new value.'
                % (name, 'expires at %s' % before['expires_at'] if before['expires_at'] else 'does not expire', expiry))
        result.update(user_token=before, diff=dict(before=before, after=before))
        return result

    # None that works: the ones that stopped working go, and a new one takes the name.
    before = view(named[0], now) if named else {}
    for token in named:
        revoke(module, client, token)
    after = dict(name=name, expires_at=expiry, expired=False)
    if not module.check_mode:
        body = dict(name=name)
        if expiry is not None:
            body['expires_at'] = expiry
        created = client.post('/user/tokens', body) or {}
        result['token'] = created.get('id') or ''
        if not result['token']:
            raise ValueError('Semaphore answered the creation of token %r without a token.' % name)
        after = view(created, now)
    result.update(changed=True, user_token=after, diff=dict(before=before, after=after))
    return result


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        expires_at=dict(type='str'),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True, **semaphore_module_kwargs())
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
