#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: integration
short_description: Manage integrations (inbound webhooks) in a Semaphore UI project
version_added: 0.1.0
description:
  - Creates, updates or deletes an integration, found by its name. An integration starts a
    template's task when its webhook URL receives a request that passes its authentication and
    matchers, and can pass values from the request to the task.
  - Makes sure the integration has a webhook URL (alias), creating one when it has none, and
    returns its URLs. Existing aliases are never removed.
  - Only the options you set are compared and changed. O(matchers) and O(extract_values), when
    set, are the complete lists. Task-parameter overrides set in Semaphore are kept as they are.
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
      - Name of the project the integration belongs to.
      - Mutually exclusive with O(project_id); one of the two is required.
    type: str
  project_id:
    description:
      - Id of the project, as an alternative to O(project).
      - With it the list of projects is not read, so a project is found on a server with 200 or more
        projects too. Semaphore cuts that list off at 200, and O(project) fails there.
      - Mutually exclusive with O(project). One of the two is required.
    type: int
    version_added: 0.3.0
  name:
    description:
      - Name of the integration. Integrations are looked up by this name within the project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the integration or updates it to match.
      - V(absent) deletes it, with its matchers, extracted values and webhook URLs.
    type: str
    choices: [present, absent]
    default: present
  template:
    description:
      - Name of the template the integration starts. Required to create an integration.
    type: str
  auth_method:
    description:
      - How requests are authenticated. V(github) and V(bitbucket) check the request's signature,
        V(hmac) an HMAC signature in the O(auth_header) header, V(token) a token in the O(auth_header)
        header, V(basic) HTTP basic authentication.
      - Every method except V(none) takes its secret from the password of the O(auth_key) key, and
        V(basic) also its user name from the key's login.
      - Defaults to V(none) for a new integration.
    type: str
    choices: [none, github, bitbucket, hmac, token, basic]
  auth_key:
    description:
      - Name of the V(login_password) key in the project's Key Store holding the secret.
      - An empty string removes it.
    type: str
  auth_header:
    description:
      - Name of the request header holding the signature (V(hmac)) or token (V(token)).
    type: str
  searchable:
    description:
      - Whether requests to the project's shared webhook URL are checked against this integration too.
    type: bool
  matchers:
    description:
      - Conditions a request must meet to start the task, all of them. When set, the complete list;
        matchers not listed are deleted.
    type: list
    elements: dict
    suboptions:
      name:
        description: Name of the matcher.
        type: str
        required: true
      match_type:
        description: Match against a V(body) field or a V(header).
        type: str
        choices: [body, header]
        default: body
      method:
        description: How the value is compared.
        type: str
        choices: [equals, unequals, contains]
        default: equals
      body_data_type:
        description: How the body is read, for O(matchers[].match_type=body).
        type: str
        choices: [json, string]
        default: json
      key:
        description: JSON path (body) or header name to read.
        type: str
        required: true
      value:
        description: Value to compare with.
        type: str
        required: true
  extract_values:
    description:
      - Values taken from the request and passed to the task. When set, the complete list; values
        not listed are deleted.
    type: list
    elements: dict
    suboptions:
      name:
        description: Name of the extracted value.
        type: str
        required: true
      value_source:
        description: Take the value from the V(body) or a V(header).
        type: str
        choices: [body, header]
        default: body
      body_data_type:
        description: How the body is read, for O(extract_values[].value_source=body).
        type: str
        choices: [json, string]
        default: json
      key:
        description: JSON path (body with V(json)) or header name to read.
        type: str
        default: ''
      variable:
        description: Name the value is passed to the task as.
        type: str
        required: true
      variable_type:
        description: Pass it as an V(environment) variable or a V(task) (extra) variable.
        type: str
        choices: [environment, task]
        default: environment
seealso:
  - module: ramanavelineni.semaphoreui.integration_info
    description: Reads integrations without changing them.
  - module: ramanavelineni.semaphoreui.template
    description: Manages the template an integration starts.
  - module: ramanavelineni.semaphoreui.key_store
    description: Manages the key that holds an integration's secret.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Run harbor_config when GitHub reports a push to main
  ramanavelineni.semaphoreui.integration:
    project: homelab
    name: gh-push
    template: harbor_config
    auth_method: github
    auth_key: github-webhook-secret
    matchers:
      - name: main-branch
        key: ref
        value: refs/heads/main
    extract_values:
      - name: commit
        key: after
        variable: COMMIT_SHA
  register: hook

- name: Show the URL to give GitHub
  ansible.builtin.debug:
    msg: "{{ hook.webhook_urls[0] }}"
'''

RETURN = r'''
integration:
  description:
    - The integration after the change, or as it would be in check mode.
    - Empty after a deletion.
  returned: always
  type: dict
  contains:
    id:
      description: Integration id.
      type: int
    name:
      description: Name of the integration.
      type: str
    template:
      description: Name of the template the integration starts.
      type: str
    auth_method:
      description: How requests are authenticated. V(none) when they are not.
      type: str
    auth_key:
      description: Name of the key that holds the secret. Null when there is none.
      type: str
    auth_header:
      description: Name of the request header with the signature or token. Empty when not set.
      type: str
    searchable:
      description: Whether requests to the project's shared webhook URL are checked against this integration too.
      type: bool
    matchers:
      description: Conditions a request must meet to start the task, sorted by name.
      type: list
      elements: dict
      contains:
        name:
          description: Name of the matcher.
          type: str
        match_type:
          description: Whether a V(body) field or a V(header) is matched.
          type: str
        method:
          description: How the value is compared (V(equals), V(unequals) or V(contains)).
          type: str
        body_data_type:
          description: How the body is read (V(json) or V(string)). Empty for a header.
          type: str
        key:
          description: JSON path or header name that is read.
          type: str
        value:
          description: Value it is compared with.
          type: str
    extract_values:
      description: Values taken from the request and passed to the task, sorted by name.
      type: list
      elements: dict
      contains:
        name:
          description: Name of the extracted value.
          type: str
        value_source:
          description: Whether the value is taken from the V(body) or a V(header).
          type: str
        body_data_type:
          description: How the body is read (V(json) or V(string)). Empty for a header.
          type: str
        key:
          description: JSON path or header name that is read.
          type: str
        variable:
          description: Name the value is passed to the task as.
          type: str
        variable_type:
          description: Whether it is passed as an V(environment) variable or a V(task) (extra) variable.
          type: str
    project_id:
      description: Id of the project.
      type: int
  sample:
    id: 1
    name: gh-push
    template: harbor_config
    auth_method: github
    auth_key: github-webhook-secret
    auth_header: ""
    searchable: false
    matchers:
      - name: main-branch
        match_type: body
        method: equals
        body_data_type: json
        key: ref
        value: refs/heads/main
    extract_values: []
    project_id: 1
webhook_urls:
  description:
    - The integration's webhook URLs. Empty in check mode for a new integration.
    - With C(auth_method) V(none), anyone who knows a URL can start the task. Set C(no_log) on the task to
      keep the URLs out of the output.
  returned: always
  type: list
  elements: str
  sample: ["https://semaphore.example.com/api/integrations/Kx8t3VqfL2cM9aZp"]
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    MATCHER_FIELDS,
    MissingReference,
    NO_AUTH,
    PROJECT_OPTIONS,
    VALUE_FIELDS,
    find_by_name,
    integration_view,
    item_view,
    project_ref,
    refuse_delete_if_used,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def validate(params):
    for option in ('matchers', 'extract_values'):
        names = [i['name'] for i in params[option] or []]
        if len(names) != len(set(names)):
            raise ValueError('%s names must be unique.' % option)
    for value in params['extract_values'] or []:
        needs_key = value['value_source'] == 'header' or value['body_data_type'] == 'json'
        if needs_key and not value['key']:
            raise ValueError('Extracted value %r needs key.' % value['name'])


def sync_items(client, path, current, desired, fields, create_status, integ_id, check_mode):
    """Make the sub-resources at `path` exactly `desired` (matched by name)."""
    have = dict((i.get('name'), i) for i in current)
    changed = False
    for item in desired:
        existing = have.pop(item['name'], None)
        body = dict((f, item[f]) for f in ('name',) + fields)
        body['integration_id'] = integ_id
        if existing is None:
            changed = True
            if not check_mode:
                client.post(path, body, expected=create_status)
        elif item_view(existing, fields) != item_view(body, fields):
            changed = True
            if not check_mode:
                body['id'] = existing['id']
                client.put('%s/%d' % (path, existing['id']), body)
    for extra in have.values():
        changed = True
        if not check_mode:
            client.delete('%s/%d' % (path, extra['id']))
    return changed


def ensure(module, client):
    params = module.params
    validate(params)
    client.warn_if_untested()

    project_id, project = project_ref(client, params, missing_ok=params['state'] == 'absent')
    if project_id is None:
        # The project is gone, and everything in it went with it.
        return dict(changed=False, integration={}, webhook_urls=[], diff=dict(before={}, after={}))
    base = '/project/%d' % project_id
    templates = client.list(base + '/templates')
    keys = client.list(base + '/keys')
    tpl_names = dict((t['id'], t['name']) for t in templates)
    key_names = dict((k['id'], k['name']) for k in keys)
    found = find_by_name(client.list(base + '/integrations'), params['name'], 'integration')

    if params['state'] == 'absent' and not found:
        return dict(changed=False, integration={}, webhook_urls=[], diff=dict(before={}, after={}))

    def ref(what, items, name):
        item = find_by_name(items, name, what)
        if item is None:
            raise MissingReference('%s %r does not exist in project %r.' % (what.capitalize(), name, project))
        return item['id']

    if found:
        # The single read carries the task-parameter overrides, which the
        # update would unlink if they were left out.
        current = client.get('%s/integrations/%d' % (base, found['id'])) or {}
        ipath = '%s/integrations/%d' % (base, current['id'])
        cur_matchers = client.list(ipath + '/matchers')
        cur_values = client.list(ipath + '/values')
    else:
        current, ipath, cur_matchers, cur_values = {}, None, [], []
    before = integration_view(current, tpl_names, key_names, cur_matchers, cur_values) if found else {}

    if params['state'] == 'absent':
        refuse_delete_if_used(client, ipath, 'integration', params['name'])
        if not module.check_mode:
            client.delete(ipath)
        return dict(changed=True, integration={}, webhook_urls=[], diff=dict(before=before, after={}))

    body = dict(current) if found else dict(auth_method='', auth_header='', searchable=False)
    body.update(project_id=project_id, name=params['name'])
    if params['template'] is not None:
        body['template_id'] = ref('template', templates, params['template'])
    if params['auth_method'] is not None:
        body['auth_method'] = '' if params['auth_method'] == NO_AUTH else params['auth_method']
    if params['auth_key'] is not None:
        body['auth_secret_id'] = ref('key', keys, params['auth_key']) if params['auth_key'] else None
    if params['auth_header'] is not None:
        body['auth_header'] = params['auth_header']
    if params['searchable'] is not None:
        body['searchable'] = params['searchable']

    matchers = params['matchers'] if params['matchers'] is not None else [item_view(m, MATCHER_FIELDS) for m in cur_matchers]
    values = params['extract_values'] if params['extract_values'] is not None else [item_view(v, VALUE_FIELDS) for v in cur_values]
    after = integration_view(body, tpl_names, key_names, matchers, values)

    method = after['auth_method']
    if method != NO_AUTH and not after['auth_key']:
        raise ValueError('auth_method %s needs auth_key.' % method)
    if method in ('hmac', 'token') and not after['auth_header']:
        raise ValueError('auth_method %s needs auth_header.' % method)

    if not found:
        if params['template'] is None:
            raise ValueError('Creating integration %r needs template.' % params['name'])
        after.pop('id')
        urls = []
        if not module.check_mode:
            created = client.post(base + '/integrations', body)
            ipath = '%s/integrations/%d' % (base, created['id'])
            sync_items(client, ipath + '/matchers', [], params['matchers'] or [], MATCHER_FIELDS, (200,), created['id'], False)
            sync_items(client, ipath + '/values', [], params['extract_values'] or [], VALUE_FIELDS, (201,), created['id'], False)
            alias = client.post(ipath + '/aliases', {}, expected=(200,))
            urls = [alias.get('url')]
            after['id'] = created['id']
        return dict(changed=True, integration=after, webhook_urls=urls, diff=dict(before={}, after=after))

    changed = False
    fields_changed = dict((k, v) for k, v in after.items() if k not in ('matchers', 'extract_values')) != \
        dict((k, v) for k, v in before.items() if k not in ('matchers', 'extract_values'))
    if fields_changed:
        changed = True
        if not module.check_mode:
            client.put(ipath, body)
    if params['matchers'] is not None:
        changed |= sync_items(client, ipath + '/matchers', cur_matchers, params['matchers'], MATCHER_FIELDS,
                              (200,), current['id'], module.check_mode)
    if params['extract_values'] is not None:
        changed |= sync_items(client, ipath + '/values', cur_values, params['extract_values'], VALUE_FIELDS,
                              (201,), current['id'], module.check_mode)

    aliases = client.list(ipath + '/aliases')
    if not aliases:
        changed = True
        if not module.check_mode:
            aliases = [client.post(ipath + '/aliases', {}, expected=(200,))]
    return dict(changed=changed, integration=after, webhook_urls=[a.get('url') for a in aliases],
                diff=dict(before=before, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str'),
        project_id=dict(type='int'),
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        template=dict(type='str'),
        auth_method=dict(type='str', choices=['none', 'github', 'bitbucket', 'hmac', 'token', 'basic']),
        auth_key=dict(type='str', no_log=False),
        auth_header=dict(type='str'),
        searchable=dict(type='bool'),
        matchers=dict(type='list', elements='dict', options=dict(
            name=dict(type='str', required=True),
            match_type=dict(type='str', default='body', choices=['body', 'header']),
            method=dict(type='str', default='equals', choices=['equals', 'unequals', 'contains']),
            body_data_type=dict(type='str', default='json', choices=['json', 'string']),
            key=dict(type='str', required=True, no_log=False),
            value=dict(type='str', required=True),
        )),
        extract_values=dict(type='list', elements='dict', options=dict(
            name=dict(type='str', required=True),
            value_source=dict(type='str', default='body', choices=['body', 'header']),
            body_data_type=dict(type='str', default='json', choices=['json', 'string']),
            key=dict(type='str', default='', no_log=False),
            variable=dict(type='str', required=True),
            variable_type=dict(type='str', default='environment', choices=['environment', 'task']),
        )),
    )
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: ensure(module, client), placeholder=dict(integration={}, webhook_urls=[]))


if __name__ == '__main__':
    main()
