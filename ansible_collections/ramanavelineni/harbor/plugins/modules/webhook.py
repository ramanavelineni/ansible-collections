#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: webhook
short_description: Manage webhooks of a Harbor project
version_added: 0.1.0
description:
  - Creates, updates or deletes a webhook (a notification policy) of a Harbor project, found by its
    name within the project. A webhook sends the chosen project events to one endpoint.
  - Only the options you set are compared and changed; the others keep their current value.
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
  project:
    description:
      - Name of the project the webhook belongs to.
    type: str
    required: true
  name:
    description:
      - Name of the webhook. Webhooks are looked up by this name within the project.
      - Renaming is not supported. A different name is a different webhook.
    type: str
    required: true
  state:
    description:
      - V(present) creates the webhook or updates it to match.
      - V(absent) deletes it.
    type: str
    choices: [present, absent]
    default: present
  description:
    description:
      - Free-text description.
    type: str
  enabled:
    description:
      - Whether the webhook sends notifications. Defaults to V(true) for a new webhook.
    type: bool
  event_types:
    description:
      - The events that trigger a notification. Required to create a webhook.
      - Compared as a set; the order does not matter.
      - Harbor 2.14 and 2.15 offer V(PUSH_ARTIFACT), V(PULL_ARTIFACT), V(DELETE_ARTIFACT), V(QUOTA_EXCEED),
        V(QUOTA_WARNING), V(SCANNING_FAILED), V(SCANNING_STOPPED), V(SCANNING_COMPLETED), V(REPLICATION) and
        V(TAG_RETENTION).
      - Any other event is checked against the events the server itself offers for the project, so one a newer
        Harbor adds can be used. An event the server does not offer fails the task; in check mode it is a
        warning instead.
    type: list
    elements: str
  notify_type:
    description:
      - V(http) posts the event as JSON to O(address); V(slack) posts a message to a Slack incoming
        webhook URL. Defaults to V(http) for a new webhook.
    type: str
    choices: [http, slack]
  address:
    description:
      - The endpoint URL the notifications are sent to. Required to create a webhook.
    type: str
  auth_header:
    description:
      - Value of the C(Authorization) header sent with each notification, for example
        C(Bearer <token>). An empty string removes it.
      - Harbor returns the stored value, so it is compared like any other option. It is never
        included in the module's result.
    type: str
  skip_cert_verify:
    description:
      - Send notifications without verifying the endpoint's TLS certificate. This is the opposite
        of the UI's I(Verify Remote Certificate).
    type: bool
  payload_format:
    description:
      - Format of the V(http) notification body. Harbor uses V(Default) for a new V(http) webhook.
      - Not allowed for V(slack).
    type: str
    choices: [Default, CloudEvents]
notes:
  - The module manages webhooks with one endpoint, which is what the Harbor UI creates. It fails
    rather than guess when a webhook made through the API has several endpoints and a target option
    is set.
  - Harbor resets a webhook's creation time on every update.
'''

EXAMPLES = r'''
- name: Tell CI about pushed and deleted artifacts
  ramanavelineni.harbor.webhook:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    name: ci-notify
    event_types: [PUSH_ARTIFACT, DELETE_ARTIFACT]
    address: https://ci.example.com/hooks/harbor
    auth_header: "Bearer {{ ci_webhook_token }}"

- name: Pause the webhook
  ramanavelineni.harbor.webhook:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    name: ci-notify
    enabled: false
'''

RETURN = r'''
webhook:
  description:
    - The webhook after the change, or as it would be in check mode. The auth header itself is never
      returned; C(auth_header_set) says whether one is stored.
    - After a change it is read back from Harbor, so it shows what Harbor stored. If that differs from what
      the task sent, the module warns, because the next run will then report a change again.
    - Empty after a deletion.
  returned: always
  type: dict
  sample:
    id: 3
    name: ci-notify
    project: apps
    project_id: 2
    description: ""
    enabled: true
    event_types: [DELETE_ARTIFACT, PUSH_ARTIFACT]
    notify_type: http
    address: https://ci.example.com/hooks/harbor
    auth_header_set: true
    skip_cert_verify: false
    payload_format: Default
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    HarborError,
    find_by_name,
    harbor_argument_spec,
    id_from_location,
    run_module,
    warn_if_stored_differently,
    webhook_view as view,
)

# The events Harbor 2.14 and 2.15 offer (GET /projects/<id>/webhook/events).
# These are accepted without asking the server.
EVENT_TYPES = ['PUSH_ARTIFACT', 'PULL_ARTIFACT', 'DELETE_ARTIFACT', 'QUOTA_EXCEED', 'QUOTA_WARNING', 'SCANNING_FAILED',
               'SCANNING_STOPPED', 'SCANNING_COMPLETED', 'REPLICATION', 'TAG_RETENTION']
TARGET_OPTIONS = ('notify_type', 'address', 'auth_header', 'skip_cert_verify', 'payload_format')


def resolve_project(client, name):
    project = find_by_name(client.list('/projects', params=dict(name=name)), name, 'project')
    if project is None:
        raise ValueError('Project %r does not exist, or the user this module logs in as cannot see it.' % name)
    return project['project_id']


def check_event_types(module, client, project_id, wanted):
    """Refuse an event the server does not offer.

    Only events outside EVENT_TYPES are looked up, so a task that uses the
    known ones costs no request more. When the server's list cannot be read,
    the event is sent as it is and Harbor decides.
    """
    unknown = set(wanted) - set(EVENT_TYPES)
    if not unknown:
        return
    try:
        answer = client.get('/projects/%d/webhook/events' % project_id)
    except HarborError:
        return
    offered = answer.get('event_type') if isinstance(answer, dict) else None
    if not isinstance(offered, list):
        return
    unknown = sorted(unknown - set(offered))
    if not unknown:
        return
    message = 'Unknown event types %s; this server offers %s.' % (', '.join(unknown), ', '.join(sorted(offered)))
    if not module.check_mode:
        raise ValueError(message)
    module.warn(message)


def comparable(targets):
    """Targets with Harbor's omitted defaults filled in, so equal ones compare equal."""
    return [dict(type=t.get('type') or 'http', address=t.get('address') or '', auth_header=t.get('auth_header') or '',
                 skip_cert_verify=bool(t.get('skip_cert_verify', False)), payload_format=t.get('payload_format') or '')
            for t in targets]


def build_target(current, params):
    """The single target with the options set applied on top of `current`."""
    target = dict(current or {})
    if params['notify_type'] is not None:
        target['type'] = params['notify_type']
    target.setdefault('type', 'http')
    if params['address'] is not None:
        target['address'] = params['address']
    if params['auth_header'] is not None:
        if params['auth_header']:
            target['auth_header'] = params['auth_header']
        else:
            target.pop('auth_header', None)
    if params['skip_cert_verify'] is not None:
        target['skip_cert_verify'] = params['skip_cert_verify']
    if params['payload_format'] is not None:
        target['payload_format'] = params['payload_format']
    if target['type'] == 'slack':
        if params['payload_format'] is not None:
            raise ValueError('payload_format is not allowed for a slack webhook.')
        # A payload format left over from an http target would be refused.
        target.pop('payload_format', None)
    elif not target.get('payload_format'):
        target['payload_format'] = 'Default'
    return target


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    project_id = resolve_project(client, params['project'])
    base = '/projects/%d/webhook/policies' % project_id
    current = find_by_name(client.list(base), params['name'], 'webhook')
    before = view(current, params['project']) if current else {}

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, webhook={}, diff=dict(before={}, after={}))
        if not module.check_mode:
            client.delete('%s/%d' % (base, current['id']))
        return dict(changed=True, webhook={}, diff=dict(before=before, after={}))

    if params['event_types']:
        check_event_types(module, client, project_id, params['event_types'])

    targets = list((current or {}).get('targets') or [])
    if any(params[o] is not None for o in TARGET_OPTIONS):
        if len(targets) > 1:
            raise ValueError(
                'Webhook %r has %d endpoints; this module manages webhooks with one endpoint (as the Harbor '
                'UI creates them). Remove the extra endpoints in Harbor, or delete the webhook and create it '
                'again.' % (params['name'], len(targets)))
        targets = [build_target(targets[0] if targets else None, params)]

    if not current:
        missing = [o for o in ('event_types', 'address') if not params[o]]
        if missing:
            raise ValueError('Creating webhook %r needs %s.' % (params['name'], ', '.join(missing)))
        body = dict(name=params['name'], description=params['description'] or '',
                    enabled=True if params['enabled'] is None else params['enabled'],
                    event_types=sorted(set(params['event_types'])), targets=targets)
        after = view(dict(body, project_id=project_id), params['project'])
        if not module.check_mode:
            dummy, headers = client.post(base, body)
            webhook_id = id_from_location(headers)
            created = client.get('%s/%d' % (base, webhook_id)) if webhook_id else \
                find_by_name(client.list(base), params['name'], 'webhook')
            after = view(created, params['project'])
        return dict(changed=True, webhook=after, diff=dict(before={}, after=after))

    body = dict(name=params['name'],
                description=current.get('description') or '' if params['description'] is None else params['description'],
                enabled=current.get('enabled', False) if params['enabled'] is None else params['enabled'],
                event_types=sorted(set(current.get('event_types') or []) if params['event_types'] is None
                                   else set(params['event_types'])),
                targets=targets)
    after = view(dict(current, **body), params['project'])
    # The auth header is left out of the view, so compare the targets themselves too.
    if after == before and comparable(body['targets']) == comparable(current.get('targets') or []):
        return dict(changed=False, webhook=before, diff=dict(before=before, after=before))
    if not module.check_mode:
        # The update replaces the whole policy: fields left out are reset
        # (enabled to false, description and auth header emptied), so the
        # current policy goes back with the changes applied.
        client.put('%s/%d' % (base, current['id']), body)
        # Read it back: the result is what Harbor stored, which is what the
        # next run compares with.
        predicted = after
        stored = client.get('%s/%d' % (base, current['id']))
        after = view(stored, params['project'])
        differing = [k for k in after if after[k] != predicted[k]]
        if not differing and comparable(stored.get('targets') or []) != comparable(body['targets']):
            # Only the auth header is compared outside the view. Its name, never its value.
            differing = ['auth_header']
        warn_if_stored_differently(module, 'webhook %r' % params['name'], differing)
    return dict(changed=True, webhook=after, diff=dict(before=before, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        description=dict(type='str'),
        enabled=dict(type='bool'),
        event_types=dict(type='list', elements='str'),
        notify_type=dict(type='str', choices=['http', 'slack']),
        address=dict(type='str'),
        auth_header=dict(type='str', no_log=True),
        skip_cert_verify=dict(type='bool'),
        payload_format=dict(type='str', choices=['Default', 'CloudEvents']),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
