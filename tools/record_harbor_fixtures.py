#!/usr/bin/env python3
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Record real Harbor API responses for the harbor collection's unit tests.

Run it against a THROWAWAY Harbor of each tested version: it creates and
deletes objects, and the system area changes global settings and schedules
before putting them back. It refuses a server that is not on this machine (a
loopback address) unless --allow-remote is passed. Pass the admin password in
HARBOR_PASSWORD:

    HARBOR_PASSWORD=<password> tools/record_harbor_fixtures.py [--allow-remote] http://127.0.0.1:8015 [AREA ...]

Responses are recorded per area (see AREAS at the bottom) and written to
ansible_collections/ramanavelineni/harbor/tests/unit/plugins/fixtures/<major.minor>/<area>.json,
one response per scenario: the status, the body and the headers the client
reads (Location, X-Total-Count), exactly as the server sent them. Without
AREA arguments every area is recorded. The unit tests load all area files of
a version as one set, so response names must be unique across areas.

To start a throwaway Harbor, see tools/harbor_up.sh.

Areas must work next to whatever else is on the server, so different areas
can be recorded one at a time or by several people at once: create what the
area needs under names of its own (starting with "fixtures-<area>"), and
delete it again.

Every area has a sweep (see SWEEPS at the bottom) that takes the area's own
objects off the server, found by the fixed names the area gives them. It runs
before the area is recorded, so what a run that died left behind is no
obstacle, and after it, also when the recording failed. A request that gets
no answer within 30 seconds fails.

Harbor locks a user for 1.5 s after a failed login and answers anonymously
meanwhile. The recorder sends two requests with a wrong password on purpose;
it waits the lock out after each, repeats a request that is answered 401, and
checks before every area that Harbor answers it as the login user. Someone
else's failed login for the same user in the middle of an area can still get
an anonymous answer recorded: read the diff of a new recording.

What is written goes into a public repository. Listings are cut down to the
objects the area created (plus Harbor's built-in "library" project), generated
robot secrets are replaced by a placeholder, the settings that describe a
site's login setup (LDAP, OIDC, UAA, auth proxy, audit log forwarding) are
recorded at their defaults whatever the server holds, and a recording in which
the admin password, a robot secret or something shaped like a credential turns
up is not written at all. Still written as the server sent them: /systeminfo
with the host name Harbor is set up with, the admin's user name as project
owner and registry credential, and the GC and log rotation history. Another
reason to use a throwaway.
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from recorder_common import TIMEOUT, keep, parse_args, require_throwaway, run_area, write_fixture

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, '..', 'ansible_collections', 'ramanavelineni', 'harbor',
                        'tests', 'unit', 'plugins', 'fixtures')
KEPT_HEADERS = ('location', 'x-total-count')
# Harbor locks a user for 1.5 s after a failed login. This is how long the
# recorder waits before it expects to be let in again, and how often it tries.
LOCK_WAIT = 2
LOCK_TRIES = 10


class Server(object):
    def __init__(self, url, username, password):
        self.url = url.rstrip('/')
        if self.url.endswith('/api/v2.0'):
            self.url = self.url[:-len('/api/v2.0')]
        self.username = username
        self.password = password
        # Live secrets of this run; a recording that holds one is not written.
        self.secrets = [password]
        self.sleep = time.sleep
        self.clock = time.monotonic
        # Until when the recorder's own last wrong-password request keeps the user locked.
        self.locked_until = 0

    def call(self, method, path, body=None, password=None):
        """One request as the login user; with password, one request with that (wrong) password.

        A request as the login user waits out the lock a wrong-password
        request of this run caused, and is sent again while Harbor answers
        401: that is the lock someone else's failed login caused. No area
        records a 401 for the right password, so nothing recorded is lost.
        """
        if password is not None:
            result = self.send(method, path, body, password)
            self.locked_until = self.clock() + LOCK_WAIT
            return result
        wait = self.locked_until - self.clock()
        if wait > 0:
            self.sleep(wait)
        for dummy in range(LOCK_TRIES):
            result = self.send(method, path, body, self.password)
            if result['status'] != 401:
                break
            self.sleep(LOCK_WAIT)
        return result

    def require_login(self):
        """Harbor's answer to /systeminfo as the login user; exits when it keeps answering anonymously.

        An anonymous answer is a 200 as well, only without harbor_version, so
        the status alone doesn't tell.
        """
        for dummy in range(LOCK_TRIES):
            info = self.call('GET', '/systeminfo')
            if info['status'] == 200 and isinstance(info['body'], dict) and info['body'].get('harbor_version'):
                return info
            self.sleep(LOCK_WAIT)
        sys.exit('Harbor does not accept the credentials: /systeminfo answers HTTP %s without harbor_version. '
                 'A wrong password, or another client keeps failing to log in as %s.' % (info['status'], self.username))

    def send(self, method, path, body, password):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + '/api/v2.0' + path, data=data, method=method)
        creds = '%s:%s' % (self.username, password)
        req.add_header('Authorization', 'Basic ' + base64.b64encode(creds.encode()).decode())
        req.add_header('Accept', 'application/json')
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
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


# Harbor's own project, on every server; listings keep it next to the area's projects.
BUILT_IN_PROJECT = 'library'


def named(*names):
    """Filter for keep(): items with one of these names."""
    return lambda item: item['name'] in names


def named_like(prefix):
    """Filter for keep(): items whose name starts with the prefix."""
    return lambda item: item['name'].startswith(prefix)


def projects_named(srv, name):
    """The projects with exactly this name (?name= also finds names that merely contain it)."""
    listed = expect(srv.call('GET', '/projects?name=%s&page=1&page_size=100' % name), 200, 'projects named %s' % name)
    return [p for p in listed['body'] or [] if p['name'] == name]


def delete_projects(srv, *names):
    """Delete the projects with exactly these names."""
    for name in names:
        for project in projects_named(srv, name):
            expect(srv.call('DELETE', '/projects/%d' % project['project_id']), 200, 'delete leftover project %s' % name)


def delete_named_like(srv, path, prefix):
    """Delete the registries or replication rules (path) whose name starts with the prefix."""
    for item in expect(srv.call('GET', path + '?page=1&page_size=100'), 200, path)['body'] or []:
        if item['name'].startswith(prefix):
            expect(srv.call('DELETE', '%s/%d' % (path, item['id'])), 200, 'delete leftover %s' % item['name'])


CORE_PROJECTS = ('fixtures-core-proxy', 'fixtures-core')
CORE_PREFIX = 'fixtures-core'


def sweep_core(srv):
    """Delete the two projects of the core area and its registry endpoint."""
    # The proxy-cache project first: its endpoint can't go while the project uses it.
    delete_projects(srv, *CORE_PROJECTS)
    delete_named_like(srv, '/registries', CORE_PREFIX)


def record_core(srv, out):
    """System info, projects, quotas and a proxy-cache project."""
    own_projects = named(BUILT_IN_PROJECT, *CORE_PROJECTS)
    own_registries = named_like(CORE_PREFIX)
    out['systeminfo'] = srv.require_login()
    out['systeminfo_anonymous'] = expect(srv.call('GET', '/systeminfo', password='wrong'), 200, 'systeminfo bad password')

    out['projects_before'] = keep(expect(srv.call('GET', '/projects?page=1&page_size=100'), 200, 'projects'), own_projects)
    out['registries_empty'] = keep(expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries'),
                                   own_registries)
    created = expect(srv.call('POST', '/projects', {
        'project_name': 'fixtures-core', 'metadata': {'public': 'false', 'auto_scan': 'true'},
        'storage_limit': 5 * 1024 ** 3}), 201, 'create project')
    out['project_create'] = created
    pid = project_id_of(created)
    out['project_create_conflict'] = srv.call('POST', '/projects', {'project_name': 'fixtures-core'})
    out['project_get'] = expect(srv.call('GET', '/projects/%d' % pid), 200, 'project')
    out['projects_with_created'] = keep(expect(srv.call('GET', '/projects?page=1&page_size=100'), 200, 'projects'),
                                        own_projects)
    out['quotas_created'] = expect(srv.call('GET', '/quotas?reference=project&reference_id=%d&page=1&page_size=100' % pid),
                                   200, 'quotas')
    out['quotas_all'] = keep(expect(srv.call('GET', '/quotas?reference=project&page=1&page_size=100'), 200, 'quotas'),
                             lambda quota: own_projects(quota['ref']))
    quota_id = out['quotas_created']['body'][0]['id']
    out['project_update'] = expect(srv.call('PUT', '/projects/%d' % pid, {
        'metadata': {'public': 'true', 'severity': 'high'}}), 200, 'update project')
    out['project_get_updated'] = expect(srv.call('GET', '/projects/%d' % pid), 200, 'project')
    out['projects_with_updated'] = keep(expect(srv.call('GET', '/projects?page=1&page_size=100'), 200, 'projects'),
                                        own_projects)
    out['quota_update'] = expect(srv.call('PUT', '/quotas/%d' % quota_id, {'hard': {'storage': -1}}), 200, 'update quota')
    out['quotas_created_updated'] = expect(srv.call('GET', '/quotas?reference=project&reference_id=%d&page=1&page_size=100' % pid),
                                           200, 'quotas')

    registry = expect(srv.call('POST', '/registries', {
        'name': 'fixtures-core-hub', 'type': 'docker-hub', 'url': 'https://hub.docker.com'}), 201, 'create registry')
    rid = project_id_of(registry)
    out['registries_one'] = keep(expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries'),
                                 own_registries)
    proxy = expect(srv.call('POST', '/projects', {
        'project_name': 'fixtures-core-proxy', 'metadata': {'public': 'true'}, 'registry_id': rid}), 201, 'create proxy project')
    out['project_create_proxy'] = proxy
    out['project_get_proxy'] = expect(srv.call('GET', '/projects/%d' % project_id_of(proxy)), 200, 'proxy project')
    expect(srv.call('DELETE', '/projects/%d' % project_id_of(proxy)), 200, 'delete proxy project')
    expect(srv.call('DELETE', '/registries/%d' % rid), 200, 'delete registry')

    out['project_delete'] = expect(srv.call('DELETE', '/projects/%d' % pid), 200, 'delete project')
    out['project_delete_missing'] = srv.call('DELETE', '/projects/%d' % pid)


# Harbor returns a webhook's auth header, which is a credential.
SECRET_KEY = re.compile(r'(secret|password|token|auth_header)$', re.I)

# Stands in for the secrets Harbor generates for new robot accounts: they are
# live credentials, so they are never written.
RECORDED_SECRET = 'RecordedSecret0'


def without_secret(result):
    """The response with any generated robot secret replaced by RECORDED_SECRET."""
    body = result.get('body')
    if isinstance(body, dict) and body.get('secret'):
        result = dict(result, body=dict(body, secret=RECORDED_SECRET))
    return result


ROBOT_PROJECT = 'fixtures-robot'


def sweep_robot(srv):
    """Delete the system robots named *fixtures-robot*, and project fixtures-robot with its robots."""
    for robot in expect(srv.call('GET', '/robots?q=name%3D~fixtures-robot&page=1&page_size=100'), 200, 'robots')['body'] or []:
        expect(srv.call('DELETE', '/robots/%d' % robot['id']), 200, 'delete leftover robot')
    for project in projects_named(srv, ROBOT_PROJECT):
        robots = expect(srv.call('GET', '/robots?q=Level%%3Dproject%%2CProjectID%%3D%d&page=1&page_size=100'
                                 % project['project_id']), 200, 'project robots')
        for robot in robots['body'] or []:
            expect(srv.call('DELETE', '/robots/%d' % robot['id']), 200, 'delete leftover project robot')
    delete_projects(srv, ROBOT_PROJECT)


def record_robot(srv, out):
    """System and project robot accounts, in project fixtures-robot."""
    project_name = ROBOT_PROJECT
    config = expect(srv.call('GET', '/configurations'), 200, 'configurations')
    # Only the setting the modules read; the rest of the configuration is
    # not the robot area's business.
    out['robot_configurations'] = dict(config, body=dict(robot_name_prefix=config['body']['robot_name_prefix']))
    out['robot_configurations_forbidden'] = srv.call('GET', '/configurations', password='wrong')
    project = expect(srv.call('POST', '/projects', {'project_name': project_name, 'metadata': {'public': 'false'}}),
                     201, 'create project')
    pid = project_id_of(project)
    # ?name= also finds projects whose name merely contains this one.
    out['robot_projects_by_name'] = keep(expect(srv.call('GET', '/projects?name=%s&page=1&page_size=100' % project_name),
                                                200, 'projects by name'), named(project_name))
    q_system = 'q=Level%3Dsystem%2Cname%3Dfixtures-robot-sys&page=1&page_size=100'
    out['robot_list_system_empty'] = expect(srv.call('GET', '/robots?' + q_system), 200, 'robots')
    perms = [{'kind': 'project', 'namespace': '*', 'access': [{'resource': 'repository', 'action': 'pull'}]}]
    created = expect(srv.call('POST', '/robots', {
        'name': 'fixtures-robot-sys', 'description': 'pulls', 'level': 'system', 'duration': -1, 'disable': False,
        'permissions': perms}), 201, 'create robot')
    srv.secrets.append(created['body']['secret'])
    out['robot_create'] = without_secret(created)
    rid = created['body']['id']
    out['robot_create_conflict'] = srv.call('POST', '/robots', {
        'name': 'fixtures-robot-sys', 'level': 'system', 'duration': -1, 'permissions': perms})
    out['robot_create_bad_name'] = srv.call('POST', '/robots', {
        'name': 'Fixtures-Robot', 'level': 'system', 'duration': -1, 'permissions': perms})
    out['robot_get'] = expect(srv.call('GET', '/robots/%d' % rid), 200, 'robot')
    out['robot_list_system'] = expect(srv.call('GET', '/robots?' + q_system), 200, 'robots')
    out['robot_list_system_all'] = keep(expect(srv.call('GET', '/robots?q=Level%3Dsystem&page=1&page_size=100'), 200, 'robots'),
                                        lambda robot: robot['id'] == rid)
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
    srv.secrets.append(pcreated['body']['secret'])
    out['robot_create_project'] = without_secret(pcreated)
    out['robot_get_project'] = expect(srv.call('GET', '/robots/%d' % pcreated['body']['id']), 200, 'project robot')
    out['robot_list_project'] = expect(srv.call('GET', '/robots?q=Level%%3Dproject%%2CProjectID%%3D%d&page=1&page_size=100' % pid),
                                       200, 'project robots')
    out['robot_delete'] = expect(srv.call('DELETE', '/robots/%d' % pcreated['body']['id']), 200, 'delete project robot')
    expect(srv.call('DELETE', '/robots/%d' % rid), 200, 'delete robot')
    out['robot_get_deleted'] = srv.call('GET', '/robots/%d' % rid)


WEBHOOK_PROJECT = 'fixtures-webhook'


def sweep_webhook(srv):
    """Delete project fixtures-webhook and its webhook policies."""
    for project in projects_named(srv, WEBHOOK_PROJECT):
        base = '/projects/%d/webhook/policies' % project['project_id']
        for policy in expect(srv.call('GET', base + '?page=1&page_size=100'), 200, 'webhooks')['body'] or []:
            expect(srv.call('DELETE', '%s/%d' % (base, policy['id'])), 200, 'delete leftover webhook')
    delete_projects(srv, WEBHOOK_PROJECT)


def record_webhook(srv, out):
    """Webhook policies of project fixtures-webhook (dummy endpoints nothing listens on)."""
    name = WEBHOOK_PROJECT
    pid = project_id_of(expect(srv.call('POST', '/projects', {'project_name': name, 'metadata': {'public': 'false'}}),
                               201, 'create project'))
    out['webhook_projects'] = keep(expect(srv.call('GET', '/projects?name=%s&page=1&page_size=100' % name), 200, 'projects'),
                                   named(name))
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


REGISTRY_PREFIX = 'rr-fixtures'


def sweep_registry(srv):
    """Delete the replication rules and registry endpoints named rr-fixtures*."""
    # Rules first: an endpoint can't go while a rule uses it.
    delete_named_like(srv, '/replication/policies', REGISTRY_PREFIX)
    delete_named_like(srv, '/registries', REGISTRY_PREFIX)


def record_registry(srv, out):
    """Registry endpoints and replication rules (objects named rr-fixtures-*).

    Harbor pings an endpoint whenever it is created or changed, so the
    endpoints point at the Harbor itself (http://proxy:8080 from inside its
    own network) and at Docker Hub. Rules are created disabled and manual,
    so nothing runs.
    """
    pw = srv.password
    # Endpoints and rules are global; other people's stay out of the recording.
    own = named_like(REGISTRY_PREFIX)

    # The registry types this Harbor can replicate with: what a module would check a type against.
    out['registry_replication_adapters'] = expect(srv.call('GET', '/replication/adapters'), 200, 'replication adapters')
    out['registry_list_before'] = keep(expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries'), own)
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
    out['registry_list'] = keep(expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries'), own)
    out['registry_update'] = expect(srv.call('PUT', '/registries/%d' % rid, {'description': 'updated'}), 200, 'update registry')
    out['registry_update_bad_secret'] = srv.call('PUT', '/registries/%d' % aid, {'access_secret': 'not-a-real-secret'})
    out['registry_get_updated'] = expect(srv.call('GET', '/registries/%d' % rid), 200, 'registry')
    out['registry_list_updated'] = keep(expect(srv.call('GET', '/registries?page=1&page_size=100'), 200, 'registries'), own)

    out['registry_replication_list_before'] = keep(
        expect(srv.call('GET', '/replication/policies?page=1&page_size=100'), 200, 'rules'), own)
    pull = {'name': 'rr-fixtures-pull', 'src_registry': {'id': rid}, 'dest_namespace': 'library', 'enabled': False,
            'override': True, 'trigger': {'type': 'manual'},
            'filters': [{'type': 'name', 'value': 'library/**'}, {'type': 'tag', 'value': 'v*', 'decoration': 'excludes'}]}
    rule = expect(srv.call('POST', '/replication/policies', pull), 201, 'create rule')
    out['registry_replication_create'] = rule
    pid = project_id_of(rule)
    out['registry_replication_create_conflict'] = srv.call('POST', '/replication/policies', pull)
    out['registry_replication_get'] = expect(srv.call('GET', '/replication/policies/%d' % pid), 200, 'rule')
    out['registry_replication_list'] = keep(
        expect(srv.call('GET', '/replication/policies?page=1&page_size=100'), 200, 'rules'), own)
    out['registry_replication_update'] = expect(srv.call('PUT', '/replication/policies/%d' % pid, dict(
        pull, speed=256, trigger={'type': 'scheduled', 'trigger_settings': {'cron': '0 0 3 * * *'}})), 200, 'update rule')
    out['registry_replication_update_bad_cron'] = srv.call('PUT', '/replication/policies/%d' % pid, dict(
        pull, trigger={'type': 'scheduled', 'trigger_settings': {'cron': '0 * * * * *'}}))
    out['registry_replication_get_updated'] = expect(srv.call('GET', '/replication/policies/%d' % pid), 200, 'rule')
    out['registry_replication_list_updated'] = keep(
        expect(srv.call('GET', '/replication/policies?page=1&page_size=100'), 200, 'rules'), own)
    out['registry_delete_in_use'] = srv.call('DELETE', '/registries/%d' % rid)
    out['registry_replication_delete'] = expect(srv.call('DELETE', '/replication/policies/%d' % pid), 200, 'delete rule')
    out['registry_delete'] = expect(srv.call('DELETE', '/registries/%d' % rid), 200, 'delete registry')
    expect(srv.call('DELETE', '/registries/%d' % aid), 200, 'delete registry with credential')


TAG_POLICY_PROJECT = 'fixtures-tag-policy'


def sweep_tag_policy(srv):
    """Delete project fixtures-tag-policy with its retention policy and immutability rules."""
    for project in projects_named(srv, TAG_POLICY_PROJECT):
        pid = project['project_id']
        retention = (project.get('metadata') or {}).get('retention_id')
        if retention:
            # Not checked: a policy that is already gone is as good.
            srv.call('DELETE', '/retentions/%s' % retention)
        base = '/projects/%d/immutabletagrules' % pid
        for rule in expect(srv.call('GET', base + '?page=1&page_size=100'), 200, 'immutable rules')['body'] or []:
            expect(srv.call('DELETE', '%s/%d' % (base, rule['id'])), 200, 'delete leftover immutable rule')
    delete_projects(srv, TAG_POLICY_PROJECT)


def record_tag_policy(srv, out):
    """Tag retention and tag immutability, in project fixtures-tag-policy."""
    call = srv.call
    name = TAG_POLICY_PROJECT
    created = expect(call('POST', '/projects', {'project_name': name, 'metadata': {'public': 'false'}}),
                     201, 'create project')
    out['tag_project_create'] = created
    pid = project_id_of(created)
    out['tag_projects_list'] = keep(expect(call('GET', '/projects?page=1&page_size=100'), 200, 'projects'),
                                    named(name, BUILT_IN_PROJECT))
    out['tag_project_get'] = expect(call('GET', '/projects/%d' % pid), 200, 'project')
    out['tag_retention_metadatas'] = expect(call('GET', '/retentions/metadatas'), 200, 'retention metadatas')

    def rule(template, value=None, tags='**', repos='**', tag_dec='matches', repo_dec='repoMatches',
             untagged=False, disabled=False):
        return {'disabled': disabled, 'action': 'retain', 'template': template,
                'params': {} if value is None else {template: value},
                'tag_selectors': [{'kind': 'doublestar', 'decoration': tag_dec, 'pattern': tags,
                                   'extras': json.dumps({'untagged': untagged})}],
                'scope_selectors': {'repository': [{'kind': 'doublestar', 'decoration': repo_dec, 'pattern': repos}]}}

    policy = {'algorithm': 'or', 'scope': {'level': 'project', 'ref': pid},
              'trigger': {'kind': 'Schedule', 'settings': {'cron': ''}},
              'rules': [rule('latestPushedK', 10)]}
    created = expect(call('POST', '/retentions', policy), 201, 'create retention')
    out['tag_retention_create'] = created
    rid = project_id_of(created)
    out['tag_project_get_with_retention'] = expect(call('GET', '/projects/%d' % pid), 200, 'project')
    out['tag_retention_get'] = expect(call('GET', '/retentions/%d' % rid), 200, 'retention')
    out['tag_retention_create_again'] = call('POST', '/retentions', policy)
    updated = dict(policy, trigger={'kind': 'Schedule', 'settings': {'cron': '0 0 3 * * *'}},
                   rules=[rule('latestPushedK', 10),
                          rule('nDaysSinceLastPull', 180, tags='v*', repos='app/**', untagged=True),
                          rule('always', tags='tmp-*', tag_dec='excludes', repo_dec='repoExcludes', disabled=True)])
    out['tag_retention_update'] = expect(call('PUT', '/retentions/%d' % rid, updated), 200, 'update retention')
    out['tag_retention_get_updated'] = expect(call('GET', '/retentions/%d' % rid), 200, 'retention')
    out['tag_retention_update_bad_cron'] = call('PUT', '/retentions/%d' % rid, dict(
        updated, trigger={'kind': 'Schedule', 'settings': {'cron': 'nope'}}))
    out['tag_retention_update_duplicate'] = call('PUT', '/retentions/%d' % rid, dict(
        policy, rules=[rule('latestPushedK', 10), rule('latestPushedK', 10)]))
    out['tag_retention_delete'] = expect(call('DELETE', '/retentions/%d' % rid), 200, 'delete retention')
    out['tag_project_get_after_retention_delete'] = expect(call('GET', '/projects/%d' % pid), 200, 'project')

    base = '/projects/%d/immutabletagrules' % pid
    immutable = {'disabled': False, 'action': 'immutable', 'template': 'immutable_template',
                 'tag_selectors': [{'kind': 'doublestar', 'decoration': 'matches', 'pattern': 'v*'}],
                 'scope_selectors': {'repository': [{'kind': 'doublestar', 'decoration': 'repoMatches', 'pattern': '**'}]}}
    out['tag_immutability_list_empty'] = expect(call('GET', base + '?page=1&page_size=100'), 200, 'immutable rules')
    created = expect(call('POST', base, immutable), 201, 'create immutable rule')
    out['tag_immutability_create'] = created
    iid = project_id_of(created)
    out['tag_immutability_create_duplicate'] = call('POST', base, immutable)
    out['tag_immutability_list_one'] = expect(call('GET', base + '?page=1&page_size=100'), 200, 'immutable rules')
    out['tag_immutability_toggle'] = expect(call('PUT', '%s/%d' % (base, iid), dict(immutable, id=iid, disabled=True)),
                                            200, 'disable immutable rule')
    out['tag_immutability_list_disabled'] = expect(call('GET', base + '?page=1&page_size=100'), 200, 'immutable rules')
    out['tag_immutability_delete'] = expect(call('DELETE', '%s/%d' % (base, iid)), 200, 'delete immutable rule')
    out['tag_immutability_delete_missing'] = call('DELETE', '%s/%d' % (base, iid))


# Settings that describe how a site logs its users in and where it sends its
# audit log: host names, search DNs, client ids, certificates.
SITE_SETTINGS = re.compile(r'^(ldap|oidc|uaa|http_authproxy)_|^audit_log_forward_endpoint$')
# What an untouched Harbor holds in the ones that aren't empty.
SITE_SETTING_DEFAULTS = dict(ldap_uid='cn', ldap_group_membership_attribute='memberof', oidc_extra_redirect_parms='{}')


def without_site_settings(result):
    """A /configurations response with the text of every site setting back at its default.

    The settings stay in the recording, because the modules read the whole
    list; what a real server has in them does not belong in a fixture.
    Numbers and switches are kept.
    """
    body = dict(result['body'])
    for name, setting in body.items():
        if SITE_SETTINGS.search(name) and isinstance(setting, dict) and isinstance(setting.get('value'), str):
            body[name] = dict(setting, value=SITE_SETTING_DEFAULTS.get(name, ''))
    return dict(result, body=body)


# What the system area sets, which is how its sweep knows them again, and what
# an untouched Harbor 2.14 or 2.15 holds in the two settings.
SYSTEM_BANNER = 'fixtures-system'
SYSTEM_SETTING_DEFAULTS = dict(banner_message='', session_timeout=60)
SYSTEM_GC_CRON = '0 0 4 * * 0'
SYSTEM_PURGE_CRON = '0 0 6 * * *'
NO_GC_SCHEDULE = {'schedule': {'type': 'None'}}
NO_PURGE_SCHEDULE = {'schedule': {'type': 'None'}, 'parameters': {'audit_retention_hour': 720, 'include_event_types': ''}}


def schedule_cron(result):
    """The cron expression of a recorded schedule, or None when no schedule is set."""
    return ((result['body'] or {}).get('schedule') or {}).get('cron')


def sweep_system(srv):
    """Take back what a system recording that died left: its banner and its two schedules.

    Only what carries the area's own values is touched: the banner text it
    sets, and a GC or log rotation schedule with exactly its cron expression.
    The settings go back to Harbor's defaults then, because what they were
    before that run is not known any more.
    """
    config = expect(srv.call('GET', '/configurations'), 200, 'configurations')
    if (config['body'].get('banner_message') or {}).get('value') == SYSTEM_BANNER:
        expect(srv.call('PUT', '/configurations', SYSTEM_SETTING_DEFAULTS), 200, 'reset the settings of an earlier run')
    if schedule_cron(expect(srv.call('GET', '/system/gc/schedule'), 200, 'gc schedule')) == SYSTEM_GC_CRON:
        expect(srv.call('PUT', '/system/gc/schedule', NO_GC_SCHEDULE), 200, 'remove leftover gc schedule')
    if schedule_cron(expect(srv.call('GET', '/system/purgeaudit/schedule'), 200, 'purge schedule')) == SYSTEM_PURGE_CRON:
        expect(srv.call('PUT', '/system/purgeaudit/schedule', NO_PURGE_SCHEDULE), 200, 'remove leftover purge schedule')


def record_system(srv, out):
    """Configuration and the GC / Scan All / log rotation schedules.

    All of these are global, so the area puts back what it changes: the
    settings it touches and the GC and log rotation schedules. It never sends
    schedule type Manual, which would start a run. Scan All can only be
    recorded as refused, because it needs a vulnerability scanner.
    """
    config = expect(srv.call('GET', '/configurations'), 200, 'configurations')
    banner = config['body']['banner_message']['value']
    session = config['body']['session_timeout']['value']
    gc_before = expect(srv.call('GET', '/system/gc/schedule'), 200, 'gc schedule')
    purge_before = expect(srv.call('GET', '/system/purgeaudit/schedule'), 200, 'purge schedule')
    if gc_before['body'] or purge_before['body']:
        sys.exit('the GC or log rotation schedule is set; record the system area on a server without them')

    out['system_configurations'] = without_site_settings(config)
    try:
        out['system_configurations_update'] = expect(srv.call('PUT', '/configurations', {
            'banner_message': SYSTEM_BANNER, 'session_timeout': 45}), 200, 'update configurations')
        out['system_configurations_updated'] = without_site_settings(
            expect(srv.call('GET', '/configurations'), 200, 'configurations'))
        out['system_configurations_bad_value'] = srv.call('PUT', '/configurations', {'session_timeout': 0})
        out['system_configurations_bad_type'] = srv.call('PUT', '/configurations', {'session_timeout': 'abc'})
    finally:
        # Here and not in the sweep, which only knows Harbor's defaults: this puts back what the server had.
        expect(srv.call('PUT', '/configurations', {'banner_message': banner, 'session_timeout': session}),
               200, 'restore configurations')
    out['system_event_types'] = expect(srv.call('GET', '/auditlog-exts/events'), 200, 'audit event types')

    try:
        out['system_gc_schedule_none'] = gc_before
        out['system_gc_schedule_update'] = expect(srv.call('PUT', '/system/gc/schedule', {
            'schedule': {'type': 'Custom', 'cron': SYSTEM_GC_CRON},
            'parameters': {'delete_untagged': True, 'workers': 2}}), 200, 'set gc schedule')
        out['system_gc_schedule_custom'] = expect(srv.call('GET', '/system/gc/schedule'), 200, 'gc schedule')
        out['system_gc_schedule_bad_cron'] = srv.call('PUT', '/system/gc/schedule', {
            'schedule': {'type': 'Custom', 'cron': '0 4 * * 0'}})
        out['system_gc_history'] = expect(srv.call('GET', '/system/gc?page=1&page_size=10&sort=-creation_time'),
                                          200, 'gc history')
        out['system_purge_schedule_none'] = purge_before
        out['system_purge_schedule_no_parameters'] = srv.call('PUT', '/system/purgeaudit/schedule', {
            'schedule': {'type': 'Custom', 'cron': SYSTEM_PURGE_CRON}})
        out['system_purge_schedule_update'] = expect(srv.call('PUT', '/system/purgeaudit/schedule', {
            'schedule': {'type': 'Custom', 'cron': SYSTEM_PURGE_CRON},
            'parameters': {'audit_retention_hour': 720, 'include_event_types': 'create_artifact,delete_artifact'}}),
            200, 'set purge schedule')
        out['system_purge_schedule_custom'] = expect(srv.call('GET', '/system/purgeaudit/schedule'), 200, 'purge schedule')
        out['system_purge_history'] = expect(srv.call('GET', '/system/purgeaudit?page=1&page_size=10&sort=-creation_time'),
                                             200, 'purge history')
        out['system_scan_all_no_scanner'] = srv.call('GET', '/system/scanAll/schedule')
    finally:
        expect(srv.call('PUT', '/system/gc/schedule', NO_GC_SCHEDULE), 200, 'remove gc schedule')
        expect(srv.call('PUT', '/system/purgeaudit/schedule', NO_PURGE_SCHEDULE), 200, 'remove purge schedule')


# Area name -> recorder. Each writes fixtures/<major.minor>/<area>.json.
AREAS = {
    'core': record_core,
    'robot': record_robot,
    'registry': record_registry,
    'webhook': record_webhook,
    'tag_policy': record_tag_policy,
    'system': record_system,
}
# Area name -> what takes the area's own objects off the server (see run_area).
SWEEPS = {
    'core': sweep_core,
    'robot': sweep_robot,
    'registry': sweep_registry,
    'webhook': sweep_webhook,
    'tag_policy': sweep_tag_policy,
    'system': sweep_system,
}


def main():
    url, areas, allow_remote = parse_args(sys.argv, AREAS)
    require_throwaway(url, allow_remote)
    password = os.environ.get('HARBOR_PASSWORD')
    if not password:
        sys.exit('set HARBOR_PASSWORD to the admin password')
    srv = Server(url, os.environ.get('HARBOR_USERNAME', 'admin'), password)
    version = srv.require_login()['body']['harbor_version']
    minor = re.match(r'^v?(\d+\.\d+)', version).group(1)

    for area in areas:
        out = {}
        # Each area starts from a request that is known to be answered as the login user.
        srv.require_login()
        run_area(area, AREAS[area], SWEEPS[area], srv, out)
        path = os.path.normpath(os.path.join(FIXTURES, minor, '%s.json' % area))
        write_fixture(path, version, out, srv.secrets, placeholders=(RECORDED_SECRET,), secret_key=SECRET_KEY)


if __name__ == '__main__':
    main()
