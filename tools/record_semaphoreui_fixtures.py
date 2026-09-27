#!/usr/bin/env python3
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Record real Semaphore API responses for the semaphoreui unit tests.

Run it against a THROWAWAY server: it creates and deletes objects. Start one
per tested version, for example with podman:

    podman run -d --name semfx -p 127.0.0.1:3019:3000 \\
        -e SEMAPHORE_DB_DIALECT=sqlite -e SEMAPHORE_ADMIN=admin \\
        -e SEMAPHORE_ADMIN_PASSWORD=<password> -e SEMAPHORE_ADMIN_NAME=Admin \\
        -e SEMAPHORE_ADMIN_EMAIL=admin@localhost \\
        docker.io/semaphoreui/semaphore:v2.19.12

    SEMAPHORE_PASSWORD=<password> tools/record_semaphoreui_fixtures.py http://127.0.0.1:3019

The output goes to
ansible_collections/ramanavelineni/semaphoreui/tests/unit/plugins/fixtures/<major.minor>.json,
one response per scenario, with the status and body exactly as the server
sent them. Nothing secret is written: the server is throwaway and no
response carries a password or token.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, '..', 'ansible_collections', 'ramanavelineni', 'semaphoreui',
                        'tests', 'unit', 'plugins', 'fixtures')


class Server(object):
    def __init__(self, url):
        self.url = url.rstrip('/')
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method, path, body=None, token=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + '/api' + path, data=data, method=method)
        req.add_header('Accept', 'application/json')
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        if token:
            req.add_header('Authorization', 'Bearer ' + token)
        try:
            with self.opener.open(req) as resp:
                status, raw = resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read().decode()
        try:
            parsed = json.loads(raw) if raw.strip() else None
        except ValueError:
            parsed = raw
        return dict(status=status, body=parsed)


def expect(result, status, what):
    if result['status'] != status:
        sys.exit('%s: expected HTTP %s, got %s: %s' % (what, status, result['status'], result['body']))
    return result


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: %s <server url>' % sys.argv[0])
    password = os.environ.get('SEMAPHORE_PASSWORD')
    if not password:
        sys.exit('set SEMAPHORE_PASSWORD to the admin password')
    username = os.environ.get('SEMAPHORE_USERNAME', 'admin')
    srv = Server(sys.argv[1])
    out = {}

    out['login_bad_password'] = expect(srv.call('POST', '/auth/login', {'auth': username, 'password': 'wrong'}), 401, 'bad login')
    out['login'] = expect(srv.call('POST', '/auth/login', {'auth': username, 'password': password}), 204, 'login')

    out['info'] = expect(srv.call('GET', '/info'), 200, 'info')
    version = out['info']['body']['version']
    minor = re.match(r'^v?(\d+\.\d+)', version).group(1)
    out['apps'] = expect(srv.call('GET', '/apps'), 200, 'apps')

    existing = expect(srv.call('GET', '/projects'), 200, 'projects')['body'] or []
    if existing:
        sys.exit('The server already has projects (%s); use a fresh throwaway server.'
                 % ', '.join(p['name'] for p in existing))
    out['projects_empty'] = expect(srv.call('GET', '/projects'), 200, 'projects')

    created = expect(srv.call('POST', '/projects', {'name': 'homelab', 'alert': False, 'max_parallel_tasks': 0}),
                     201, 'create project')
    out['project_create'] = created
    pid = created['body']['id']
    out['projects_one'] = expect(srv.call('GET', '/projects'), 200, 'projects')

    out['project_update_id_mismatch'] = srv.call(
        'PUT', '/project/%d' % pid, {'id': pid + 1000, 'name': 'homelab'})
    out['project_update'] = expect(srv.call(
        'PUT', '/project/%d' % pid,
        {'id': pid, 'name': 'homelab', 'alert': True, 'alert_chat': 'ops', 'max_parallel_tasks': 3}),
        204, 'update project')
    out['projects_one_updated'] = expect(srv.call('GET', '/projects'), 200, 'projects')

    # API token auth, checked here so the recording fails if it ever breaks.
    token = expect(srv.call('POST', '/user/tokens'), 201, 'create token')['body']['id']
    expect(srv.call('GET', '/info', token=token), 200, 'info with token')
    expect(srv.call('DELETE', '/user/tokens/%s' % token), 204, 'delete token')

    out['project_delete'] = expect(srv.call('DELETE', '/project/%d' % pid), 204, 'delete project')
    out['logout'] = expect(srv.call('POST', '/auth/logout'), 204, 'logout')

    path = os.path.normpath(os.path.join(FIXTURES, '%s.json' % minor))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(dict(recorded_from=version, responses=out), f, indent=2, sort_keys=True)
        f.write('\n')
    print('wrote %s (%d responses, server %s)' % (path, len(out), version))


if __name__ == '__main__':
    main()
