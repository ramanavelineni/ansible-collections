#!/usr/bin/env python3
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Record real Harbor API responses for the harbor collection's unit tests.

Run it against a THROWAWAY Harbor of each tested version: it creates and
deletes objects. Pass the admin password in HARBOR_PASSWORD:

    HARBOR_PASSWORD=<password> tools/record_harbor_fixtures.py http://127.0.0.1:8015 [AREA ...]

Responses are recorded per area (see AREAS at the bottom) and written to
ansible_collections/ramanavelineni/harbor/tests/unit/plugins/fixtures/<major.minor>/<area>.json,
one response per scenario: the status, the body and the headers the client
reads (Location, X-Total-Count), exactly as the server sent them. Without
AREA arguments every area is recorded. The unit tests load all area files of
a version as one set, so response names must be unique across areas.

Areas must work next to whatever else is on the server, so they can be
recorded one at a time or by several people at once: create what the area
needs under names of its own (starting with "fixtures-<area>"), and delete
it again.

Nothing secret is written: the server is throwaway and no response carries a
password or robot secret.
"""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, '..', 'ansible_collections', 'ramanavelineni', 'harbor',
                        'tests', 'unit', 'plugins', 'fixtures')
KEPT_HEADERS = ('location', 'x-total-count')


class Server(object):
    def __init__(self, url, username, password):
        self.url = url.rstrip('/')
        if self.url.endswith('/api/v2.0'):
            self.url = self.url[:-len('/api/v2.0')]
        self.username = username
        self.password = password

    def call(self, method, path, body=None, password=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + '/api/v2.0' + path, data=data, method=method)
        creds = '%s:%s' % (self.username, self.password if password is None else password)
        req.add_header('Authorization', 'Basic ' + base64.b64encode(creds.encode()).decode())
        req.add_header('Accept', 'application/json')
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req) as resp:
                status, raw, headers = resp.status, resp.read().decode(), resp.headers
        except urllib.error.HTTPError as e:
            status, raw, headers = e.code, e.read().decode(), e.headers
        try:
            parsed = json.loads(raw) if raw.strip() else None
        except ValueError:
            parsed = raw
        kept = dict((k.lower(), v) for k, v in headers.items() if k.lower() in KEPT_HEADERS)
        return dict(status=status, body=parsed, headers=kept)


def expect(result, status, what):
    if result['status'] != status:
        sys.exit('%s: expected HTTP %s, got %s: %s' % (what, status, result['status'], result['body']))
    return result


def project_id_of(created):
    return int(created['headers']['location'].rstrip('/').rsplit('/', 1)[-1])


def record_core(srv, out):
    """System info, projects, quotas and a proxy-cache project."""
    out['systeminfo'] = expect(srv.call('GET', '/systeminfo'), 200, 'systeminfo')
    out['systeminfo_anonymous'] = expect(srv.call('GET', '/systeminfo', password='wrong'), 200, 'systeminfo bad password')
    for name in ('fixtures-core', 'fixtures-core-proxy'):
        found = [p for p in srv.call('GET', '/projects?name=%s' % name)['body'] or [] if p['name'] == name]
        if found:
            sys.exit('project %s exists from an earlier run; delete it first' % name)

    out['projects_before'] = expect(srv.call('GET', '/projects?page=1&page_size=100'), 200, 'projects')
    out['registries_empty'] = expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries')
    created = expect(srv.call('POST', '/projects', {
        'project_name': 'fixtures-core', 'metadata': {'public': 'false', 'auto_scan': 'true'},
        'storage_limit': 5 * 1024 ** 3}), 201, 'create project')
    out['project_create'] = created
    pid = project_id_of(created)
    out['project_create_conflict'] = srv.call('POST', '/projects', {'project_name': 'fixtures-core'})
    out['project_get'] = expect(srv.call('GET', '/projects/%d' % pid), 200, 'project')
    out['projects_with_created'] = expect(srv.call('GET', '/projects?page=1&page_size=100'), 200, 'projects')
    out['quotas_created'] = expect(srv.call('GET', '/quotas?reference=project&reference_id=%d&page=1&page_size=100' % pid),
                                   200, 'quotas')
    out['quotas_all'] = expect(srv.call('GET', '/quotas?reference=project&page=1&page_size=100'), 200, 'quotas')
    quota_id = out['quotas_created']['body'][0]['id']
    out['project_update'] = expect(srv.call('PUT', '/projects/%d' % pid, {
        'metadata': {'public': 'true', 'severity': 'high'}}), 200, 'update project')
    out['project_get_updated'] = expect(srv.call('GET', '/projects/%d' % pid), 200, 'project')
    out['projects_with_updated'] = expect(srv.call('GET', '/projects?page=1&page_size=100'), 200, 'projects')
    out['quota_update'] = expect(srv.call('PUT', '/quotas/%d' % quota_id, {'hard': {'storage': -1}}), 200, 'update quota')
    out['quotas_created_updated'] = expect(srv.call('GET', '/quotas?reference=project&reference_id=%d&page=1&page_size=100' % pid),
                                           200, 'quotas')

    registry = expect(srv.call('POST', '/registries', {
        'name': 'fixtures-core-hub', 'type': 'docker-hub', 'url': 'https://hub.docker.com'}), 201, 'create registry')
    rid = project_id_of(registry)
    out['registries_one'] = expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries')
    proxy = expect(srv.call('POST', '/projects', {
        'project_name': 'fixtures-core-proxy', 'metadata': {'public': 'true'}, 'registry_id': rid}), 201, 'create proxy project')
    out['project_create_proxy'] = proxy
    out['project_get_proxy'] = expect(srv.call('GET', '/projects/%d' % project_id_of(proxy)), 200, 'proxy project')
    expect(srv.call('DELETE', '/projects/%d' % project_id_of(proxy)), 200, 'delete proxy project')
    expect(srv.call('DELETE', '/registries/%d' % rid), 200, 'delete registry')

    out['project_delete'] = expect(srv.call('DELETE', '/projects/%d' % pid), 200, 'delete project')
    out['project_delete_missing'] = srv.call('DELETE', '/projects/%d' % pid)


# Stands in for the secrets Harbor generates for new robot accounts: they are
# live credentials, so they are never written.
RECORDED_SECRET = 'RecordedSecret0'


def without_secret(result):
    """The response with any generated robot secret replaced by RECORDED_SECRET."""
    body = result.get('body')
    if isinstance(body, dict) and body.get('secret'):
        result = dict(result, body=dict(body, secret=RECORDED_SECRET))
    return result


def record_robot(srv, out):
    """System and project robot accounts, in project fixtures-robot."""
    project_name = 'fixtures-robot'
    for robot in srv.call('GET', '/robots?q=name%3D~fixtures-robot&page=1&page_size=100')['body'] or []:
        expect(srv.call('DELETE', '/robots/%d' % robot['id']), 200, 'delete leftover robot')
    for p in srv.call('GET', '/projects?name=%s' % project_name)['body'] or []:
        if p['name'] == project_name:
            for robot in srv.call('GET', '/robots?q=Level%%3Dproject%%2CProjectID%%3D%d' % p['project_id'])['body'] or []:
                expect(srv.call('DELETE', '/robots/%d' % robot['id']), 200, 'delete leftover project robot')
            expect(srv.call('DELETE', '/projects/%d' % p['project_id']), 200, 'delete leftover project')

    config = expect(srv.call('GET', '/configurations'), 200, 'configurations')
    # Only the setting the modules read; the rest of the configuration is
    # not the robot area's business.
    out['robot_configurations'] = dict(config, body=dict(robot_name_prefix=config['body']['robot_name_prefix']))
    out['robot_configurations_forbidden'] = srv.call('GET', '/configurations', password='wrong')
    project = expect(srv.call('POST', '/projects', {'project_name': project_name, 'metadata': {'public': 'false'}}),
                     201, 'create project')
    pid = project_id_of(project)
    out['robot_projects_by_name'] = expect(srv.call('GET', '/projects?name=%s&page=1&page_size=100' % project_name),
                                           200, 'projects by name')
    q_system = 'q=Level%3Dsystem%2Cname%3Dfixtures-robot-sys&page=1&page_size=100'
    out['robot_list_system_empty'] = expect(srv.call('GET', '/robots?' + q_system), 200, 'robots')
    perms = [{'kind': 'project', 'namespace': '*', 'access': [{'resource': 'repository', 'action': 'pull'}]}]
    created = expect(srv.call('POST', '/robots', {
        'name': 'fixtures-robot-sys', 'description': 'pulls', 'level': 'system', 'duration': -1, 'disable': False,
        'permissions': perms}), 201, 'create robot')
    out['robot_create'] = without_secret(created)
    rid = created['body']['id']
    out['robot_create_conflict'] = srv.call('POST', '/robots', {
        'name': 'fixtures-robot-sys', 'level': 'system', 'duration': -1, 'permissions': perms})
    out['robot_create_bad_name'] = srv.call('POST', '/robots', {
        'name': 'Fixtures-Robot', 'level': 'system', 'duration': -1, 'permissions': perms})
    out['robot_get'] = expect(srv.call('GET', '/robots/%d' % rid), 200, 'robot')
    out['robot_list_system'] = expect(srv.call('GET', '/robots?' + q_system), 200, 'robots')
    out['robot_list_system_all'] = expect(srv.call('GET', '/robots?q=Level%3Dsystem&page=1&page_size=100'), 200, 'robots')
    current = out['robot_get']['body']
    out['robot_update'] = expect(srv.call('PUT', '/robots/%d' % rid, dict(
        current, description='pulls everything', permissions=[
            {'kind': 'project', 'namespace': project_name,
             'access': [{'resource': 'repository', 'action': 'pull'}, {'resource': 'repository', 'action': 'push'}]}])),
        200, 'update robot')
    out['robot_get_updated'] = expect(srv.call('GET', '/robots/%d' % rid), 200, 'robot')
    out['robot_update_bad_name'] = srv.call('PUT', '/robots/%d' % rid, dict(current, name='fixtures-robot-sys'))
    out['robot_secret_set'] = expect(srv.call('PATCH', '/robots/%d' % rid, {'secret': 'NotARealSecret1'}),
                                     200, 'set secret')
    out['robot_secret_weak'] = srv.call('PATCH', '/robots/%d' % rid, {'secret': 'weak'})

    project_perms = [{'kind': 'project', 'namespace': project_name,
                      'access': [{'resource': 'repository', 'action': 'pull'}]}]
    pcreated = expect(srv.call('POST', '/robots', {
        'name': 'ci', 'level': 'project', 'duration': 30, 'permissions': project_perms}), 201, 'create project robot')
    out['robot_create_project'] = without_secret(pcreated)
    out['robot_get_project'] = expect(srv.call('GET', '/robots/%d' % pcreated['body']['id']), 200, 'project robot')
    out['robot_list_project'] = expect(srv.call('GET', '/robots?q=Level%%3Dproject%%2CProjectID%%3D%d&page=1&page_size=100' % pid),
                                       200, 'project robots')
    out['robot_delete'] = expect(srv.call('DELETE', '/robots/%d' % pcreated['body']['id']), 200, 'delete project robot')
    expect(srv.call('DELETE', '/robots/%d' % rid), 200, 'delete robot')
    out['robot_get_deleted'] = srv.call('GET', '/robots/%d' % rid)


def record_webhook(srv, out):
    """Webhook policies of project fixtures-webhook (dummy endpoints nothing listens on)."""
    name = 'fixtures-webhook'
    for p in srv.call('GET', '/projects?name=%s' % name)['body'] or []:
        if p['name'] == name:
            for pol in srv.call('GET', '/projects/%d/webhook/policies' % p['project_id'])['body'] or []:
                expect(srv.call('DELETE', '/projects/%d/webhook/policies/%d' % (p['project_id'], pol['id'])),
                       200, 'delete leftover webhook')
            expect(srv.call('DELETE', '/projects/%d' % p['project_id']), 200, 'delete leftover project')
    pid = project_id_of(expect(srv.call('POST', '/projects', {'project_name': name, 'metadata': {'public': 'false'}}),
                               201, 'create project'))
    out['webhook_projects'] = expect(srv.call('GET', '/projects?name=%s&page=1&page_size=100' % name), 200, 'projects')
    base = '/projects/%d/webhook/policies' % pid
    out['webhook_events'] = expect(srv.call('GET', '/projects/%d/webhook/events' % pid), 200, 'webhook events')
    out['webhook_list_empty'] = expect(srv.call('GET', base + '?page=1&page_size=100'), 200, 'webhooks')
    policy = {'name': 'ci-notify', 'description': 'recorded', 'enabled': True,
              'event_types': ['DELETE_ARTIFACT', 'PUSH_ARTIFACT'],
              'targets': [{'type': 'http', 'address': 'http://127.0.0.1:9/hook',
                           'auth_header': 'Bearer not-a-real-token', 'skip_cert_verify': False,
                           'payload_format': 'Default'}]}
    created = expect(srv.call('POST', base, policy), 201, 'create webhook')
    out['webhook_create'] = created
    wid = project_id_of(created)
    out['webhook_get'] = expect(srv.call('GET', '%s/%d' % (base, wid)), 200, 'webhook')
    out['webhook_list_one'] = expect(srv.call('GET', base + '?page=1&page_size=100'), 200, 'webhooks')
    out['webhook_create_conflict'] = srv.call('POST', base, policy)
    out['webhook_create_bad_event'] = srv.call('POST', base, dict(policy, name='bad', event_types=['NOPE']))
    out['webhook_update'] = expect(srv.call('PUT', '%s/%d' % (base, wid), dict(policy, enabled=False)), 200,
                                   'update webhook')
    out['webhook_get_updated'] = expect(srv.call('GET', '%s/%d' % (base, wid)), 200, 'webhook')
    two = dict(policy, targets=policy['targets'] + [{'type': 'slack', 'address': 'http://127.0.0.1:9/slack'}])
    expect(srv.call('PUT', '%s/%d' % (base, wid), two), 200, 'update webhook to two targets')
    out['webhook_list_two_targets'] = expect(srv.call('GET', base + '?page=1&page_size=100'), 200, 'webhooks')
    out['webhook_delete'] = expect(srv.call('DELETE', '%s/%d' % (base, wid)), 200, 'delete webhook')
    out['webhook_delete_missing'] = srv.call('DELETE', '%s/%d' % (base, wid))
    expect(srv.call('DELETE', '/projects/%d' % pid), 200, 'delete project')


def record_registry(srv, out):
    """Registry endpoints and replication rules (objects named rr-fixtures-*).

    Harbor pings an endpoint whenever it is created or changed, so the
    endpoints point at the Harbor itself (http://proxy:8080 from inside its
    own network) and at Docker Hub. Rules are created disabled and manual,
    so nothing runs.
    """
    pw = srv.password

    def cleanup():
        for rule in srv.call('GET', '/replication/policies?page=1&page_size=100')['body'] or []:
            if rule['name'].startswith('rr-fixtures'):
                expect(srv.call('DELETE', '/replication/policies/%d' % rule['id']), 200, 'delete leftover rule')
        for reg in srv.call('GET', '/registries?page=1&page_size=100')['body'] or []:
            if reg['name'].startswith('rr-fixtures'):
                expect(srv.call('DELETE', '/registries/%d' % reg['id']), 200, 'delete leftover registry')

    cleanup()
    out['registry_list_before'] = expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries')
    created = expect(srv.call('POST', '/registries', {
        'name': 'rr-fixtures-self', 'type': 'harbor', 'url': 'http://proxy:8080', 'insecure': True}),
        201, 'create registry')
    out['registry_create'] = created
    rid = project_id_of(created)
    out['registry_create_unhealthy'] = srv.call('POST', '/registries', {
        'name': 'rr-fixtures-dummy', 'type': 'docker-registry', 'url': 'http://rr-nonexistent.invalid'})
    out['registry_create_conflict'] = srv.call('POST', '/registries', {
        'name': 'rr-fixtures-self', 'type': 'harbor', 'url': 'http://proxy:8080', 'insecure': True})
    auth = expect(srv.call('POST', '/registries', {
        'name': 'rr-fixtures-auth', 'type': 'harbor', 'url': 'http://proxy:8080', 'insecure': True,
        'credential': {'type': 'basic', 'access_key': srv.username, 'access_secret': pw}}), 201, 'create registry with credential')
    aid = project_id_of(auth)
    out['registry_get'] = expect(srv.call('GET', '/registries/%d' % rid), 200, 'registry')
    out['registry_get_with_credential'] = expect(srv.call('GET', '/registries/%d' % aid), 200, 'registry with credential')
    out['registry_list'] = expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries')
    out['registry_update'] = expect(srv.call('PUT', '/registries/%d' % rid, {'description': 'updated'}), 200, 'update registry')
    out['registry_update_bad_secret'] = srv.call('PUT', '/registries/%d' % aid, {'access_secret': 'not-a-real-secret'})
    out['registry_get_updated'] = expect(srv.call('GET', '/registries/%d' % rid), 200, 'registry')
    out['registry_list_updated'] = expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries')

    out['registry_replication_list_before'] = expect(srv.call('GET', '/replication/policies?page=1&page_size=100'), 200, 'rules')
    pull = {'name': 'rr-fixtures-pull', 'src_registry': {'id': rid}, 'dest_namespace': 'library', 'enabled': False,
            'override': True, 'trigger': {'type': 'manual'},
            'filters': [{'type': 'name', 'value': 'library/**'}, {'type': 'tag', 'value': 'v*', 'decoration': 'excludes'}]}
    rule = expect(srv.call('POST', '/replication/policies', pull), 201, 'create rule')
    out['registry_replication_create'] = rule
    pid = project_id_of(rule)
    out['registry_replication_create_conflict'] = srv.call('POST', '/replication/policies', pull)
    out['registry_replication_get'] = expect(srv.call('GET', '/replication/policies/%d' % pid), 200, 'rule')
    out['registry_replication_list'] = expect(srv.call('GET', '/replication/policies?page=1&page_size=100'), 200, 'rules')
    out['registry_replication_update'] = expect(srv.call('PUT', '/replication/policies/%d' % pid, dict(
        pull, speed=256, trigger={'type': 'scheduled', 'trigger_settings': {'cron': '0 0 3 * * *'}})), 200, 'update rule')
    out['registry_replication_update_bad_cron'] = srv.call('PUT', '/replication/policies/%d' % pid, dict(
        pull, trigger={'type': 'scheduled', 'trigger_settings': {'cron': '0 * * * * *'}}))
    out['registry_replication_get_updated'] = expect(srv.call('GET', '/replication/policies/%d' % pid), 200, 'rule')
    out['registry_replication_list_updated'] = expect(srv.call('GET', '/replication/policies?page=1&page_size=100'), 200, 'rules')
    out['registry_delete_in_use'] = srv.call('DELETE', '/registries/%d' % rid)
    out['registry_replication_delete'] = expect(srv.call('DELETE', '/replication/policies/%d' % pid), 200, 'delete rule')
    out['registry_delete'] = expect(srv.call('DELETE', '/registries/%d' % rid), 200, 'delete registry')
    expect(srv.call('DELETE', '/registries/%d' % aid), 200, 'delete registry with credential')
    cleanup()


# Area name -> recorder. Each writes fixtures/<major.minor>/<area>.json.
AREAS = {
    'core': record_core,
    'robot': record_robot,
    'registry': record_registry,
    'webhook': record_webhook,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith('-'):
        sys.exit('usage: %s <server url> [AREA ...]   (areas: %s)' % (sys.argv[0], ', '.join(sorted(AREAS))))
    areas = sys.argv[2:] or sorted(AREAS)
    unknown = [a for a in areas if a not in AREAS]
    if unknown:
        sys.exit('unknown area(s) %s; known: %s' % (', '.join(unknown), ', '.join(sorted(AREAS))))
    password = os.environ.get('HARBOR_PASSWORD')
    if not password:
        sys.exit('set HARBOR_PASSWORD to the admin password')
    srv = Server(sys.argv[1], os.environ.get('HARBOR_USERNAME', 'admin'), password)
    version = expect(srv.call('GET', '/systeminfo'), 200, 'systeminfo')['body'].get('harbor_version')
    if not version:
        sys.exit('Harbor did not accept the credentials (no harbor_version in /systeminfo)')
    minor = re.match(r'^v?(\d+\.\d+)', version).group(1)

    for area in areas:
        out = {}
        AREAS[area](srv, out)
        path = os.path.normpath(os.path.join(FIXTURES, minor, '%s.json' % area))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(dict(recorded_from=version, responses=out), f, indent=2, sort_keys=True)
            f.write('\n')
        print('wrote %s (%d responses, server %s)' % (path, len(out), version))


if __name__ == '__main__':
    main()
