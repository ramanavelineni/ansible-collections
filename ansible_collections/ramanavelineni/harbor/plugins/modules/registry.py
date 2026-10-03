#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: registry
short_description: Manage Harbor registry endpoints
version_added: 0.1.0
description:
  - Creates, updates or deletes a registry endpoint (Administration > Registries), found by its name.
    Endpoints are what proxy-cache projects and replication rules connect to.
  - Only the options you set are compared and changed; the others keep their current value.
  - Harbor never returns the endpoint's secret, so a changed secret cannot be detected. By default
    a declared secret is sent on every run and the task reports C(changed); see O(update_secret).
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
  name:
    description:
      - Name of the endpoint. Endpoints are looked up by this name.
    type: str
    required: true
  state:
    description:
      - V(present) creates the endpoint or updates it to match.
      - V(absent) deletes it. Harbor refuses while a replication rule or a proxy-cache project uses it.
    type: str
    choices: [present, absent]
    default: present
  type:
    description:
      - Provider of the endpoint. Required to create it.
      - Harbor 2.14 and 2.15 offer V(ali-acr), V(aws-ecr), V(azure-acr), V(docker-hub), V(docker-registry),
        V(github-ghcr), V(google-gcr), V(harbor), V(huawei-SWR), V(jfrog-artifactory), V(tencent-tcr) and
        V(volcengine-cr).
      - Any other type is checked against the types the server offers before the endpoint is created,
        so a type a newer Harbor adds can be used. A type the server does not offer fails; in check mode
        it is a warning instead.
      - Harbor cannot change the type of an existing endpoint, so a different type fails with
        instructions instead.
    type: str
  endpoint_url:
    description:
      - URL of the endpoint, for example C(https://hub.docker.com). Required to create it.
      - Named C(endpoint_url) because O(url) is the Harbor server this module talks to.
      - Harbor stores it without a trailing slash.
    type: str
  description:
    description:
      - Free-text description.
    type: str
  insecure:
    description:
      - Skip verifying the endpoint's TLS certificate.
    type: bool
  ca_certificate:
    description:
      - PEM-encoded CA certificate to verify the endpoint with, instead of the system CA pool.
      - Needs Harbor 2.15; Harbor 2.14 silently ignores it, so the module fails there instead.
    type: str
  credential_type:
    description:
      - How Harbor authenticates to the endpoint. V(basic) sends O(access_key) and O(access_secret) as a user
        name and password, V(oauth) as an OAuth client.
      - Defaults to V(basic) when O(access_key) or O(access_secret) is set and the endpoint has no
        credential type yet.
    type: str
    choices: [basic, oauth]
  access_key:
    description:
      - User name, access key id or similar, depending on O(type).
    type: str
  access_secret:
    description:
      - Password, token or secret key for O(access_key).
    type: str
  update_secret:
    description:
      - V(always) sends O(access_secret) on every run, so the task reports C(changed) whenever it is set.
      - V(on_create) sends it only when the endpoint is created.
    type: str
    choices: [always, on_create]
    default: always
notes:
  - Harbor checks that the endpoint is reachable (and the credentials work) whenever it is created or
    changed, and refuses with C(the registry is unhealthy) (HTTP 400), or answers HTTP 500, when it is not.
seealso:
  - module: ramanavelineni.harbor.registry_info
    description: List registry endpoints.
  - module: ramanavelineni.harbor.replication
    description: Replicate to or from an endpoint.
  - module: ramanavelineni.harbor.project
    description: Create a proxy-cache project on an endpoint.
'''

EXAMPLES = r'''
# The connection options (url, username, password) can be set once instead of on every task, with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: Docker Hub endpoint for a proxy-cache project
  ramanavelineni.harbor.registry:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    name: dockerhub
    type: docker-hub
    endpoint_url: https://hub.docker.com

- name: GitHub Container Registry with a token, set once
  ramanavelineni.harbor.registry:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    name: ghcr
    type: github-ghcr
    endpoint_url: https://ghcr.io
    access_key: my-bot
    access_secret: "{{ ghcr_token }}"
    update_secret: on_create
'''

RETURN = r'''
registry:
  description:
    - The endpoint after the change, or as it would be in check mode. The secret is never returned;
      C(has_secret) says whether one is stored.
    - After a change it is read back from Harbor, so it shows what Harbor stored. If that differs from what
      the task sent, the module warns, because the next run will then report a change again.
    - C(status) is the result of the check Harbor makes when it stores the endpoint.
    - Empty after a deletion.
  returned: always
  type: dict
  sample:
    id: 3
    name: ghcr
    type: github-ghcr
    url: https://ghcr.io
    description: ""
    insecure: false
    credential_type: basic
    access_key: my-bot
    has_secret: true
    ca_certificate: ""
    status: healthy
  contains:
    id:
      description: Harbor's id of the endpoint.
      type: int
    name:
      description: Name of the endpoint.
      type: str
    type:
      description: Provider of the endpoint, for example V(docker-hub) or V(harbor).
      type: str
    url:
      description: URL of the endpoint, without a trailing slash.
      type: str
    description:
      description: Description, empty when there is none.
      type: str
    insecure:
      description: Whether Harbor skips verifying the endpoint's TLS certificate.
      type: bool
    credential_type:
      description: How Harbor authenticates to the endpoint, for example V(basic). Empty when no credentials are stored.
      type: str
    access_key:
      description: User name or access key id Harbor logs in with, empty when there is none.
      type: str
    has_secret:
      description: Whether a secret is stored. The secret itself is never returned.
      type: bool
    ca_certificate:
      description: PEM-encoded CA certificate Harbor verifies the endpoint with, empty when there is none.
      type: str
    status:
      description: Result of Harbor's check of the endpoint, for example V(healthy) or V(unhealthy).
      type: str
secret_updated:
  description: Whether the module sent the endpoint's secret.
  returned: always
  type: bool
  sample: true
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    HarborError,
    find_by_name,
    harbor_argument_spec,
    id_from_location,
    older_than,
    run_module,
    server_minor,
    warn_if_stored_differently,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.replication import (
    REGISTRY_TYPES,
    normalize_url,
    registry_view as view,
)

# Option -> field of the registry view it is compared with.
COMPARED = (('endpoint_url', 'url'), ('description', 'description'), ('insecure', 'insecure'),
            ('credential_type', 'credential_type'), ('access_key', 'access_key'),
            ('ca_certificate', 'ca_certificate'))
# Option -> field of Harbor's update body (RegistryUpdate).
UPDATE_FIELDS = dict(endpoint_url='url', description='description', insecure='insecure',
                     credential_type='credential_type', access_key='access_key', ca_certificate='ca_certificate')


def desired_values(params):
    out = {}
    for option, field in COMPARED:
        value = params[option]
        if value is None:
            continue
        out[field] = normalize_url(value) if option == 'endpoint_url' else value
    return out


def check_type(module, client, wanted):
    """Refuse a type the server does not offer.

    Only a type outside REGISTRY_TYPES is looked up, so a task that uses a
    known one costs no request more. When the server's list cannot be read,
    the type is sent as it is and Harbor decides.
    """
    if wanted in REGISTRY_TYPES:
        return
    try:
        offered = client.get('/replication/adapters')
    except HarborError:
        return
    if not isinstance(offered, list) or wanted in offered:
        return
    message = 'Unknown registry type %s; this server offers %s.' % (
        wanted, ', '.join(sorted(str(t) for t in offered)))
    if not module.check_mode:
        raise ValueError(message)
    module.warn(message)


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    minor = server_minor(client)
    if params['ca_certificate'] is not None and older_than(minor, (2, 15)):
        raise ValueError('ca_certificate needs Harbor 2.15; Harbor %d.%d ignores it.' % minor)

    current = find_by_name(client.list('/registries'), params['name'], 'registry')
    result = dict(changed=False, registry={}, secret_updated=False)

    if params['state'] == 'absent':
        if not current:
            result.update(diff=dict(before={}, after={}))
            return result
        before = view(current)
        if not module.check_mode:
            client.delete('/registries/%d' % current['id'])
        result.update(changed=True, diff=dict(before=before, after={}))
        return result

    desired = desired_values(params)
    send_secret = params['access_secret'] is not None and (not current or params['update_secret'] == 'always')

    if not current:
        missing = [o for o in ('type', 'endpoint_url') if params[o] is None]
        if missing:
            raise ValueError('Creating registry %r needs %s.' % (params['name'], ', '.join(missing)))
        check_type(module, client, params['type'])
        body = dict(name=params['name'], type=params['type'], url=desired['url'],
                    insecure=bool(params['insecure']), description=params['description'] or '')
        if params['ca_certificate'] is not None:
            body['ca_certificate'] = params['ca_certificate']
        if params['access_key'] is not None or params['access_secret'] is not None:
            body['credential'] = dict(type=params['credential_type'] or 'basic',
                                      access_key=params['access_key'] or '',
                                      access_secret=params['access_secret'] or '')
        after = view(dict(body, credential=dict(body.get('credential') or {})))
        after.update(id=None, status='')
        if not module.check_mode:
            dummy, headers = client.post('/registries', body)
            registry_id = id_from_location(headers)
            created = client.get('/registries/%d' % registry_id) if registry_id else \
                find_by_name(client.list('/registries'), params['name'], 'registry')
            after = view(created)
        result.update(changed=True, registry=after, secret_updated=params['access_secret'] is not None,
                      diff=dict(before={}, after=after))
        return result

    before = view(current)
    if params['type'] is not None and params['type'] != before['type']:
        raise ValueError(
            'Registry %r is of type %s, but type says %s. Harbor cannot change the type of an endpoint: '
            'delete it (state: absent; first remove the replication rules and proxy-cache projects that use it) '
            'and create it again.' % (params['name'], before['type'], params['type']))

    changed = sorted(field for field, value in desired.items() if before.get(field) != value)
    if not changed and not send_secret:
        result.update(registry=before, diff=dict(before=before, after=before))
        return result

    after = dict(before)
    after.update((field, desired[field]) for field in changed)
    body = {}
    for option, field in UPDATE_FIELDS.items():
        if field in changed:
            body[field] = desired[field]
    if send_secret:
        body['access_secret'] = params['access_secret']
        after['has_secret'] = bool(params['access_secret'])
    # A key or secret without a type is stored with an empty one, which Harbor
    # cannot log in with.
    if (send_secret or body.get('access_key')) and 'credential_type' not in body and not before['credential_type']:
        body['credential_type'] = params['credential_type'] or 'basic'
        after['credential_type'] = body['credential_type']
    if not module.check_mode:
        # The update merges: only the fields in the body change. Harbor checks
        # that the endpoint is still reachable with the result.
        client.put('/registries/%d' % current['id'], body)
        # Read it back: the status is the result of that check, and what Harbor
        # stored is what the next run compares with.
        predicted = after
        after = view(client.get('/registries/%d' % current['id']))
        warn_if_stored_differently(module, 'registry %r' % params['name'],
                                   [f for f in set(changed) | {'credential_type'} if after[f] != predicted[f]])
    result.update(changed=True, registry=after, secret_updated=send_secret, diff=dict(before=before, after=after))
    return result


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        type=dict(type='str'),
        endpoint_url=dict(type='str'),
        description=dict(type='str'),
        insecure=dict(type='bool'),
        ca_certificate=dict(type='str'),
        credential_type=dict(type='str', choices=['basic', 'oauth']),
        access_key=dict(type='str', no_log=False),
        access_secret=dict(type='str', no_log=True),
        update_secret=dict(type='str', default='always', choices=['always', 'on_create'], no_log=False),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
