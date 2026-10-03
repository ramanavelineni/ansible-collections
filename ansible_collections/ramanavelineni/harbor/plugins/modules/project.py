#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: project
short_description: Manage Harbor projects
version_added: 0.1.0
description:
  - Creates, updates or deletes a Harbor project, found by its name, with its visibility, metadata,
    proxy-cache registry and storage quota.
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
  name:
    description:
      - Name of the project. Projects are looked up by this name.
      - Renaming is not supported. A different name is a different project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the project or updates it to match.
      - V(absent) deletes it. It requires O(confirm_delete=true), and fails while the project still
        holds repositories.
    type: str
    choices: [present, absent]
    default: present
  public:
    description:
      - Whether anyone may pull from the project without logging in.
      - Defaults to V(false) for a new project.
    type: bool
  metadata:
    description:
      - Project settings, by Harbor's metadata key. Only the keys given are compared and changed.
      - V(auto_scan), V(auto_sbom_generation), V(prevent_vul), V(reuse_sys_cve_allowlist),
        V(enable_content_trust), V(enable_content_trust_cosign) and V(proxy_cache_local_on_not_found)
        take booleans; V(severity) takes V(none), V(low), V(medium), V(high) or V(critical);
        V(proxy_speed_kb) and V(max_upstream_conn) take integers.
      - V(proxy_cache_local_on_not_found) needs Harbor 2.15.
      - Harbor silently ignores keys it does not know and stores an invalid severity as C(unknown),
        so the module checks keys and values before sending anything.
    type: dict
  proxy_registry:
    description:
      - Name of the registry endpoint that makes this a proxy-cache project.
      - Only used when the project is created. Harbor cannot change it later, so a project bound to
        another registry fails with instructions instead.
    type: str
  quota_gb:
    description:
      - Storage quota in GiB. V(-1) means unlimited.
    type: int
  confirm_delete:
    description:
      - Must be V(true) for O(state=absent) to delete the project.
    type: bool
    default: false
'''

EXAMPLES = r'''
- name: Private project with scanning and a 50 GiB quota
  ramanavelineni.harbor.project:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    name: apps
    metadata:
      auto_scan: true
      severity: high
      prevent_vul: true
    quota_gb: 50

- name: Proxy cache of Docker Hub
  ramanavelineni.harbor.project:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    name: proxy-docker
    public: true
    proxy_registry: dockerhub
'''

RETURN = r'''
project:
  description:
    - The project after the change, or as it would be in check mode.
    - Empty after a deletion.
  returned: always
  type: dict
  sample:
    project_id: 2
    name: apps
    public: false
    metadata:
      auto_scan: "true"
      severity: high
      prevent_vul: "true"
    proxy_registry: null
    registry_id: null
    quota_gb: 50
    repo_count: 0
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    GIB,
    find_by_name,
    harbor_argument_spec,
    id_from_location,
    project_view as view,
    run_module,
    server_minor,
)

BOOL_KEYS = ('auto_scan', 'auto_sbom_generation', 'prevent_vul', 'reuse_sys_cve_allowlist',
             'enable_content_trust', 'enable_content_trust_cosign', 'proxy_cache_local_on_not_found')
INT_KEYS = ('proxy_speed_kb', 'max_upstream_conn')
SEVERITIES = ('none', 'low', 'medium', 'high', 'critical')
# Key -> oldest (major, minor) that knows it.
NEWER_KEYS = dict(proxy_cache_local_on_not_found=(2, 15))


def normalize_metadata(metadata, minor):
    """The metadata option as Harbor stores it (all strings), after checking it."""
    out = {}
    for key, value in (metadata or {}).items():
        if key in ('public', 'retention_id'):
            raise ValueError('metadata.%s is not managed here (%s).'
                             % (key, 'use the public option' if key == 'public' else 'use the tag_retention module'))
        if key in BOOL_KEYS:
            if isinstance(value, bool):
                value = 'true' if value else 'false'
            elif str(value).lower() in ('true', 'false'):
                value = str(value).lower()
            else:
                raise ValueError('metadata.%s must be a boolean, not %r.' % (key, value))
        elif key == 'severity':
            value = str(value).lower()
            if value == 'negligible':
                value = 'none'
            if value not in SEVERITIES:
                raise ValueError('metadata.severity must be one of %s, not %r.' % (', '.join(SEVERITIES), value))
        elif key in INT_KEYS:
            try:
                value = str(int(value))
            except (TypeError, ValueError):
                raise ValueError('metadata.%s must be an integer, not %r.' % (key, value))
        else:
            raise ValueError('metadata.%s is not a Harbor project setting (known: %s).'
                             % (key, ', '.join(sorted(BOOL_KEYS + INT_KEYS + ('severity',)))))
        needs = NEWER_KEYS.get(key)
        if needs and minor and minor < needs:
            raise ValueError('metadata.%s needs Harbor %d.%d.' % ((key,) + needs))
        out[key] = value
    return out


def quota_of(client, project_id):
    quotas = client.list('/quotas', params=dict(reference='project', reference_id=project_id))
    return quotas[0] if quotas else None


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    metadata = normalize_metadata(params['metadata'], server_minor(client))
    storage = None if params['quota_gb'] is None else (-1 if params['quota_gb'] == -1 else params['quota_gb'] * GIB)
    if params['quota_gb'] is not None and params['quota_gb'] < -1:
        raise ValueError('quota_gb must be -1 (unlimited) or a number of GiB.')

    current = find_by_name(client.list('/projects'), params['name'], 'project')
    registries = {}
    if current or params['proxy_registry']:
        registries = dict((r['id'], r['name']) for r in client.list('/registries'))

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, project={}, diff=dict(before={}, after={}))
        if not params['confirm_delete']:
            raise ValueError('Refusing to delete project %r: that deletes everything in it. Set '
                             'confirm_delete: true to delete it.' % params['name'])
        if current.get('repo_count'):
            raise ValueError('Cannot delete project %r: it still holds %d repositories, and Harbor only '
                             'deletes empty projects. Delete them first.' % (params['name'], current['repo_count']))
        before = view(current, None, registries)
        if not module.check_mode:
            client.delete('/projects/%d' % current['project_id'])
        return dict(changed=True, project={}, diff=dict(before=before, after={}))

    registry_id = None
    if params['proxy_registry']:
        registry_id = next((rid for rid, name in registries.items() if name == params['proxy_registry']), None)
        if registry_id is None:
            raise ValueError('Registry %r does not exist.' % params['proxy_registry'])

    if not current:
        body = dict(project_name=params['name'],
                    metadata=dict(metadata, public='true' if params['public'] else 'false'))
        if storage is not None:
            body['storage_limit'] = storage
        if registry_id:
            body['registry_id'] = registry_id
        after = dict(project_id=None, name=params['name'], public=bool(params['public']), metadata=metadata,
                     registry_id=registry_id, proxy_registry=params['proxy_registry'],
                     quota_gb=params['quota_gb'], repo_count=0)
        if not module.check_mode:
            dummy, headers = client.post('/projects', body)
            project_id = id_from_location(headers)
            created = client.get('/projects/%d' % project_id) if project_id else \
                find_by_name(client.list('/projects'), params['name'], 'project')
            after = view(created, quota_of(client, created['project_id']), registries)
        return dict(changed=True, project=after, diff=dict(before={}, after=after))

    project_id = current['project_id']
    quota = quota_of(client, project_id)
    if storage is not None and quota is None:
        raise ValueError('Project %r has no quota in Harbor, so quota_gb cannot be set. Remove quota_gb, or '
                         'check the project\'s quota in Harbor.' % params['name'])
    before = view(current, quota, registries)
    if params['proxy_registry'] is not None and before['registry_id'] != registry_id:
        raise ValueError(
            'Project %r is bound to registry %r, but proxy_registry says %r. Harbor cannot change a '
            'project\'s proxy-cache registry: delete the project and create it again.'
            % (params['name'], before['proxy_registry'], params['proxy_registry']))

    changed_meta = dict((k, v) for k, v in metadata.items() if before['metadata'].get(k) != v)
    if params['public'] is not None and params['public'] != before['public']:
        changed_meta['public'] = 'true' if params['public'] else 'false'
    quota_changed = storage is not None and quota is not None and quota.get('hard', {}).get('storage') != storage
    if not changed_meta and not quota_changed:
        return dict(changed=False, project=before, diff=dict(before=before, after=before))

    after = dict(before, metadata=dict(before['metadata']))
    for key, value in changed_meta.items():
        if key == 'public':
            after['public'] = value == 'true'
        else:
            after['metadata'][key] = value
    if quota_changed:
        after['quota_gb'] = params['quota_gb']
    if not module.check_mode:
        if changed_meta:
            # The update merges the given metadata keys into the project's; a
            # top-level "public" is ignored, so visibility goes in metadata too.
            client.put('/projects/%d' % project_id, dict(metadata=changed_meta))
        if quota_changed:
            client.put('/quotas/%d' % quota['id'], dict(hard=dict(storage=storage)))
    return dict(changed=True, project=after, diff=dict(before=before, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        public=dict(type='bool'),
        metadata=dict(type='dict'),
        proxy_registry=dict(type='str'),
        quota_gb=dict(type='int'),
        confirm_delete=dict(type='bool', default=False),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
