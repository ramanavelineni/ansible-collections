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


# Area name -> recorder. Each writes fixtures/<major.minor>/<area>.json.
AREAS = {
    'core': record_core,
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
