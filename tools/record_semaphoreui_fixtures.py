#!/usr/bin/env python3
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Record real Semaphore API responses for the semaphoreui unit tests.

Run it against a THROWAWAY server: it creates and deletes objects. It refuses
a server that is not on this machine (a loopback address) unless --allow-remote
is passed. Start one per tested version, for example with podman:

    podman run -d --name semfx -p 127.0.0.1:3019:3000 \\
        -e SEMAPHORE_DB_DIALECT=sqlite -e SEMAPHORE_ADMIN=admin \\
        -e SEMAPHORE_ADMIN_PASSWORD=<password> -e SEMAPHORE_ADMIN_NAME=Admin \\
        -e SEMAPHORE_ADMIN_EMAIL=admin@localhost \\
        docker.io/semaphoreui/semaphore:v2.19.12

    SEMAPHORE_PASSWORD=<password> tools/record_semaphoreui_fixtures.py [--allow-remote] http://127.0.0.1:3019 [AREA ...]

Responses are recorded per area (see AREAS at the bottom) and written to
ansible_collections/ramanavelineni/semaphoreui/tests/unit/plugins/fixtures/<major.minor>/<area>.json,
one response per scenario, with the status and body exactly as the server
sent them. Without AREA arguments every area is recorded. The unit tests
load all area files of a version as one set, so response names must be
unique across areas.

The "core" area must run on a server with no projects: it records empty
lists. Every other area has to work next to other projects, so different
areas can be recorded one at a time or by several people at once: create what
the area needs in a project of its own (named "fixtures-<area>"), and delete
it again.

Every area has a sweep (see SWEEPS at the bottom) that takes the area's own
objects off the server, found by the fixed names the area gives them. It runs
before the area is recorded, so what a run that died left behind is no
obstacle, and after it, also when the recording failed. A request that gets
no answer within 30 seconds fails.

What is written goes into a public repository. Listings are cut down to the
objects the area created, the runner registration token is replaced by a
placeholder, and a recording in which the admin password, a generated token or
something shaped like a credential turns up is not written at all. Still
written as the server sent them: /info, /apps, and the account the recorder
logs in with (username, name and e-mail). Another reason to use a throwaway.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

from recorder_common import TIMEOUT, keep, parse_args, require_throwaway, run_area, write_fixture

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, '..', 'ansible_collections', 'ramanavelineni', 'semaphoreui',
                        'tests', 'unit', 'plugins', 'fixtures')


# Not a key: Semaphore stores whatever it is given, and never returns it.
FAKE_PRIVATE_KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nnot-a-real-key\n-----END OPENSSH PRIVATE KEY-----'


class Server(object):
    def __init__(self, url):
        self.url = url.rstrip('/')
        # Live secrets of this run; a recording that holds one is not written.
        self.secrets = []
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
            with self.opener.open(req, timeout=TIMEOUT) as resp:
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


def delete_projects(srv, *names):
    """Delete the projects with exactly these names."""
    for project in expect(srv.call('GET', '/projects'), 200, 'projects')['body'] or []:
        if project['name'] in names:
            expect(srv.call('DELETE', '/project/%d' % project['id']), 204, 'delete leftover project %s' % project['name'])


# The core area's project, and what the area puts into it: (list path, name
# field, the area's names), in an order in which they can be deleted.
CORE_PROJECT = 'homelab'
CORE_CONTENTS = (
    ('integrations', 'name', ('gh',)),
    ('schedules', 'name', ('nightly', 'on-push')),
    ('templates', 'name', ('site', 'infra', 'surveyed')),
    ('inventory', 'name', ('homelab', 'abs')),
    ('environment', 'name', ('empty', 'harbor')),
    ('repositories', 'name', ('ansible',)),
    ('keys', 'name', ('deploy',)),
)


def sweep_core(srv):
    """Delete a project homelab that an earlier recording left behind.

    "homelab" is also what a real project may be called, so the name alone is
    not enough: the project is only deleted when everything in it carries a
    name the core area uses. Anything else in it stops the run.
    """
    for project in expect(srv.call('GET', '/projects'), 200, 'projects')['body'] or []:
        if project['name'] != CORE_PROJECT:
            continue
        base = '/project/%d' % project['id']
        own, foreign = [], []
        for path, field, names in CORE_CONTENTS:
            for item in expect(srv.call('GET', '%s/%s' % (base, path)), 200, path)['body'] or []:
                if item[field] in names:
                    own.append('%s/%s/%d' % (base, path, item['id']))
                else:
                    foreign.append('%s "%s"' % (path, item[field]))
        if foreign:
            sys.exit('Project %s holds things the recorder does not make (%s), so it is not what an earlier '
                     'recording left behind. Record the core area on a fresh throwaway server.'
                     % (CORE_PROJECT, ', '.join(foreign)))
        # Not checked one by one: some go with the object that owns them. Deleting the project is the check.
        for path in own:
            srv.call('DELETE', path)
        expect(srv.call('DELETE', base), 204, 'delete leftover project %s' % CORE_PROJECT)


def record_core(srv, out):
    """Info, apps, login, projects and everything inside a project.

    Needs a server without projects, because it records empty lists.
    """
    out['info'] = expect(srv.call('GET', '/info'), 200, 'info')
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
    # What the modules read when a task names the project by id (project_id).
    out['project_get'] = expect(srv.call('GET', '/project/%d' % pid), 200, 'project')

    out['project_update_id_mismatch'] = srv.call(
        'PUT', '/project/%d' % pid, {'id': pid + 1000, 'name': 'homelab'})
    out['project_update'] = expect(srv.call(
        'PUT', '/project/%d' % pid,
        {'id': pid, 'name': 'homelab', 'alert': True, 'alert_chat': 'ops', 'max_parallel_tasks': 3}),
        204, 'update project')
    out['projects_one_updated'] = expect(srv.call('GET', '/projects'), 200, 'projects')

    # API token auth, checked here so the recording fails if it ever breaks.
    token = expect(srv.call('POST', '/user/tokens'), 201, 'create token')['body']['id']
    srv.secrets.append(token)
    try:
        expect(srv.call('GET', '/info', token=token), 200, 'info with token')
    finally:
        # The sweep cannot tell this token from the account's other ones, so it goes here.
        expect(srv.call('DELETE', '/user/tokens/%s' % token), 204, 'delete token')

    # Key Store and repositories, inside the project above.
    base = '/project/%d' % pid
    out['keys_new_project'] = expect(srv.call('GET', base + '/keys'), 200, 'keys')
    out['key_create'] = expect(srv.call('POST', base + '/keys', {
        'project_id': pid, 'name': 'deploy', 'type': 'ssh',
        'ssh': {'login': 'git', 'passphrase': '', 'private_key': FAKE_PRIVATE_KEY}}), 201, 'create key')
    kid = out['key_create']['body']['id']
    out['keys_with_deploy'] = expect(srv.call('GET', base + '/keys'), 200, 'keys')
    out['key_update_id_mismatch'] = srv.call('PUT', '%s/keys/%d' % (base, kid), {
        'id': kid + 1000, 'project_id': pid, 'name': 'deploy', 'type': 'none', 'override_secret': True})
    out['key_update'] = expect(srv.call('PUT', '%s/keys/%d' % (base, kid), {
        'id': kid, 'project_id': pid, 'name': 'deploy', 'type': 'login_password', 'override_secret': True,
        'login_password': {'login': '', 'password': 'not-a-real-password'}}), 204, 'update key')
    out['keys_with_deploy_updated'] = expect(srv.call('GET', base + '/keys'), 200, 'keys')
    out['key_refs_unused'] = expect(srv.call('GET', '%s/keys/%d/refs' % (base, kid)), 200, 'key refs')

    out['repositories_empty'] = expect(srv.call('GET', base + '/repositories'), 200, 'repositories')
    out['repository_create'] = expect(srv.call('POST', base + '/repositories', {
        'project_id': pid, 'name': 'ansible', 'git_url': 'git@github.com:example/ansible.git',
        'git_branch': 'main', 'ssh_key_id': kid}), 201, 'create repository')
    rid = out['repository_create']['body']['id']
    out['repositories_one'] = expect(srv.call('GET', base + '/repositories'), 200, 'repositories')
    out['key_refs_used_by_repository'] = expect(srv.call('GET', '%s/keys/%d/refs' % (base, kid)), 200, 'key refs')
    out['key_delete_in_use'] = srv.call('DELETE', '%s/keys/%d' % (base, kid))
    # Inventories, using the key and repository above.
    out['inventories_empty'] = expect(srv.call('GET', base + '/inventory'), 200, 'inventories')
    out['inventory_create'] = expect(srv.call('POST', base + '/inventory', {
        'project_id': pid, 'name': 'homelab', 'type': 'file', 'inventory': 'inventories/homelab/hosts',
        'repository_id': rid, 'ssh_key_id': kid, 'become_key_id': None}), 201, 'create inventory')
    iid = out['inventory_create']['body']['id']
    out['inventories_one'] = expect(srv.call('GET', base + '/inventory'), 200, 'inventories')
    inv = dict(out['inventory_create']['body'])
    out['inventory_update'] = expect(srv.call('PUT', '%s/inventory/%d' % (base, iid), dict(inv, become_key_id=kid)),
                                     204, 'update inventory')
    out['inventories_one_updated'] = expect(srv.call('GET', base + '/inventory'), 200, 'inventories')
    abs_inv = expect(srv.call('POST', base + '/inventory', {
        'project_id': pid, 'name': 'abs', 'type': 'file', 'inventory': '/etc/ansible/hosts'}), 201, 'create abs inventory')
    out['inventory_update_absolute_path'] = srv.call(
        'PUT', '%s/inventory/%d' % (base, abs_inv['body']['id']), dict(abs_inv['body'], ssh_key_id=kid))
    expect(srv.call('DELETE', '%s/inventory/%d' % (base, abs_inv['body']['id'])), 204, 'delete abs inventory')
    # Views and templates, using the key, repository and inventory above.
    out['views_new_project'] = expect(srv.call('GET', base + '/views'), 200, 'views')
    out['view_create'] = expect(srv.call('POST', base + '/views', {
        'project_id': pid, 'title': 'k8s', 'position': 1}), 201, 'create view')
    vid = out['view_create']['body']['id']
    out['views_two'] = expect(srv.call('GET', base + '/views'), 200, 'views')
    out['view_update'] = expect(srv.call('PUT', '%s/views/%d' % (base, vid), {
        'id': vid, 'project_id': pid, 'title': 'k8s', 'position': 2, 'type': '', 'hidden': True}), 204, 'update view')
    env = expect(srv.call('POST', base + '/environment', {
        'project_id': pid, 'name': 'empty', 'json': '{}', 'env': '{}'}), 201, 'create environment')['body']
    out['variable_groups_for_templates'] = expect(srv.call('GET', base + '/environment'), 200, 'environments')
    out['templates_empty'] = expect(srv.call('GET', base + '/templates'), 200, 'templates')
    out['template_create'] = expect(srv.call('POST', base + '/templates', {
        'project_id': pid, 'name': 'site', 'app': 'ansible', 'playbook': 'site.yml', 'repository_id': rid,
        'inventory_id': iid, 'environment_id': env['id'], 'environment_ids': [env['id']], 'view_id': vid,
        'arguments': '["-v"]', 'task_params': {'limit': ['web']},
        'survey_vars': [{'name': 'host', 'title': 'Host', 'type': ''}],
        'vaults': [{'name': 'default', 'type': 'password', 'vault_key_id': kid}]}), 201, 'create template')
    tid = out['template_create']['body']['id']
    out['templates_one'] = expect(srv.call('GET', base + '/templates'), 200, 'templates')
    out['template_get'] = expect(srv.call('GET', '%s/templates/%d' % (base, tid)), 200, 'template')
    tpl = dict(out['template_get']['body'])
    out['template_update'] = expect(srv.call('PUT', '%s/templates/%d' % (base, tid), dict(tpl, description='updated')),
                                    204, 'update template')
    out['template_get_updated'] = expect(srv.call('GET', '%s/templates/%d' % (base, tid)), 200, 'template')
    out['template_update_id_mismatch'] = srv.call('PUT', '%s/templates/%d' % (base, tid), dict(tpl, id=tid + 1000))
    out['template_refs_unused'] = expect(srv.call('GET', '%s/templates/%d/refs' % (base, tid)), 200, 'template refs')

    # Schedules on the template above: a cron schedule and a commit poller.
    out['schedules_empty'] = expect(srv.call('GET', base + '/schedules'), 200, 'schedules')
    out['schedule_create'] = expect(srv.call('POST', base + '/schedules', {
        'project_id': pid, 'template_id': tid, 'name': 'nightly', 'cron_format': '0 3 * * *', 'active': True}),
        201, 'create schedule')
    sid = out['schedule_create']['body']['id']
    out['schedule_create_poller'] = expect(srv.call('POST', base + '/schedules', {
        'project_id': pid, 'template_id': tid, 'name': 'on-push', 'cron_format': '*/5 * * * *',
        'repository_id': rid, 'active': True}), 201, 'create poller')
    out['schedules_project_list'] = expect(srv.call('GET', base + '/schedules'), 200, 'schedules')
    out['schedules_template_pollers'] = expect(srv.call('GET', '%s/templates/%d/schedules' % (base, tid)),
                                               200, 'template schedules')
    out['schedule_get'] = expect(srv.call('GET', '%s/schedules/%d' % (base, sid)), 200, 'schedule')
    sched = dict(out['schedule_get']['body'])
    out['schedule_update'] = expect(srv.call('PUT', '%s/schedules/%d' % (base, sid), dict(sched, active=False)),
                                    204, 'update schedule')
    out['schedule_update_bad_cron'] = srv.call('PUT', '%s/schedules/%d' % (base, sid), dict(sched, cron_format='bad cron'))
    out['schedule_delete'] = expect(srv.call('DELETE', '%s/schedules/%d' % (base, sid)), 204, 'delete schedule')
    expect(srv.call('DELETE', '%s/schedules/%d' % (base, out['schedule_create_poller']['body']['id'])), 204, 'delete poller')

    # An integration on the template above, with a matcher, a value and an alias.
    out['integrations_empty'] = expect(srv.call('GET', base + '/integrations'), 200, 'integrations')
    out['integration_create'] = expect(srv.call('POST', base + '/integrations', {
        'project_id': pid, 'name': 'gh', 'template_id': tid, 'auth_method': 'token', 'auth_secret_id': kid,
        'auth_header': 'X-Token', 'searchable': False}), 201, 'create integration')
    gid = out['integration_create']['body']['id']
    ipath = '%s/integrations/%d' % (base, gid)
    out['integrations_one'] = expect(srv.call('GET', base + '/integrations'), 200, 'integrations')
    out['integration_get'] = expect(srv.call('GET', ipath), 200, 'integration')
    out['integration_matchers_empty'] = expect(srv.call('GET', ipath + '/matchers'), 200, 'matchers')
    out['integration_matcher_create'] = expect(srv.call('POST', ipath + '/matchers', {
        'integration_id': gid, 'name': 'main', 'match_type': 'body', 'method': 'equals', 'body_data_type': 'json',
        'key': 'ref', 'value': 'refs/heads/main'}), 200, 'create matcher')
    out['integration_matchers_one'] = expect(srv.call('GET', ipath + '/matchers'), 200, 'matchers')
    mid = out['integration_matcher_create']['body']['id']
    out['integration_matcher_update'] = expect(srv.call('PUT', '%s/matchers/%d' % (ipath, mid), dict(
        out['integration_matcher_create']['body'], value='refs/heads/develop')), 204, 'update matcher')
    out['integration_values_empty'] = expect(srv.call('GET', ipath + '/values'), 200, 'values')
    out['integration_value_create'] = expect(srv.call('POST', ipath + '/values', {
        'integration_id': gid, 'name': 'sha', 'value_source': 'body', 'body_data_type': 'json', 'key': 'after',
        'variable': 'COMMIT_SHA', 'variable_type': 'environment'}), 201, 'create value')
    out['integration_values_one'] = expect(srv.call('GET', ipath + '/values'), 200, 'values')
    out['integration_aliases_empty'] = expect(srv.call('GET', ipath + '/aliases'), 200, 'aliases')
    out['integration_alias_create'] = expect(srv.call('POST', ipath + '/aliases', {}), 200, 'create alias')
    out['integration_aliases_one'] = expect(srv.call('GET', ipath + '/aliases'), 200, 'aliases')
    out['integration_update'] = expect(srv.call('PUT', ipath, dict(out['integration_get']['body'], searchable=True)),
                                       204, 'update integration')
    out['integration_refs_unused'] = expect(srv.call('GET', ipath + '/refs'), 200, 'integration refs')
    out['integration_matcher_delete'] = expect(srv.call('DELETE', '%s/matchers/%d' % (ipath, mid)), 204, 'delete matcher')
    # Semaphore 2.18 and 2.19 on SQLite answer 204 to these two and remove nothing; the lists afterwards show it.
    out['integration_matchers_after_delete'] = expect(srv.call('GET', ipath + '/matchers'), 200, 'matchers')
    out['integration_value_delete'] = expect(srv.call(
        'DELETE', '%s/values/%d' % (ipath, out['integration_value_create']['body']['id'])), 204, 'delete value')
    out['integration_values_after_delete'] = expect(srv.call('GET', ipath + '/values'), 200, 'values')
    out['integration_delete'] = expect(srv.call('DELETE', ipath), 204, 'delete integration')
    tofu = expect(srv.call('POST', base + '/templates', {
        'project_id': pid, 'name': 'infra', 'app': 'tofu', 'repository_id': rid,
        'environment_id': env['id'], 'environment_ids': [env['id']]}), 201, 'create tofu template')
    out['template_create_tofu'] = tofu
    out['templates_two'] = expect(srv.call('GET', base + '/templates'), 200, 'templates')
    out['inventory_list_hides_workspace'] = expect(srv.call('GET', base + '/inventory'), 200, 'inventories')
    out['inventory_get_workspace'] = expect(srv.call('GET', '%s/inventory/%d' % (base, tofu['body']['inventory_id'])),
                                            200, 'workspace inventory')
    expect(srv.call('DELETE', '%s/templates/%d' % (base, tofu['body']['id'])), 204, 'delete tofu template')
    out['template_delete'] = expect(srv.call('DELETE', '%s/templates/%d' % (base, tid)), 204, 'delete template')

    # A survey variable with `target`, which Semaphore 2.19 has ('' or 'env') and 2.18 does not know.
    # Not checked with expect(): what each version answers is what the recording is for.
    surveyed = srv.call('POST', base + '/templates', {
        'project_id': pid, 'name': 'surveyed', 'app': 'ansible', 'playbook': 'site.yml', 'repository_id': rid,
        'inventory_id': iid, 'environment_id': env['id'], 'environment_ids': [env['id']],
        'survey_vars': [{'name': 'region', 'title': 'Region', 'type': '', 'target': 'env'}]})
    out['template_create_survey_target'] = surveyed
    if surveyed['status'] == 201:
        spath = '%s/templates/%d' % (base, surveyed['body']['id'])
        out['template_get_survey_target'] = expect(srv.call('GET', spath), 200, 'template with survey target')
        # The template goes back as it was read, with only the description changed.
        out['template_update_survey_target'] = srv.call(
            'PUT', spath, dict(out['template_get_survey_target']['body'], description='updated'))
        out['template_get_survey_target_updated'] = expect(srv.call('GET', spath), 200, 'template with survey target')
        expect(srv.call('DELETE', spath), 204, 'delete template with survey target')
    expect(srv.call('DELETE', '%s/environment/%d' % (base, env['id'])), 204, 'delete environment')
    out['view_delete'] = expect(srv.call('DELETE', '%s/views/%d' % (base, vid)), 204, 'delete view')

    out['inventory_refs_unused'] = expect(srv.call('GET', '%s/inventory/%d/refs' % (base, iid)), 200, 'inventory refs')
    out['inventory_delete'] = expect(srv.call('DELETE', '%s/inventory/%d' % (base, iid)), 204, 'delete inventory')

    # Variable groups (environments) and their secrets.
    out['variable_groups_empty'] = expect(srv.call('GET', base + '/environment'), 200, 'environments')
    out['variable_group_create'] = expect(srv.call('POST', base + '/environment', {
        'project_id': pid, 'name': 'harbor', 'json': '{"harbor_url": "https://harbor.example.com"}',
        'env': '{"TZ": "UTC"}', 'secrets': [
            {'name': 'TOKEN', 'type': 'env', 'secret': 'not-a-real-token', 'operation': 'create'},
            {'name': 'db_pw', 'type': 'var', 'secret': 'not-a-real-password', 'operation': 'create'}]}),
        201, 'create environment')
    eid = out['variable_group_create']['body']['id']
    out['variable_groups_one'] = expect(srv.call('GET', base + '/environment'), 200, 'environments')
    out['variable_group_get'] = expect(srv.call('GET', '%s/environment/%d' % (base, eid)), 200, 'environment')
    token = [s for s in out['variable_group_get']['body']['secrets'] if s['name'] == 'TOKEN'][0]
    group = dict(out['variable_group_get']['body'])
    group.pop('secrets')
    out['variable_group_update'] = expect(srv.call('PUT', '%s/environment/%d' % (base, eid), dict(
        group, env='{"TZ": "Europe/Oslo"}', secrets=[
            dict(id=token['id'], name='TOKEN', type='env', secret='', operation='delete'),
            dict(name='TOKEN', type='var', secret='not-a-real-token', operation='create')])),
        204, 'update environment')
    out['variable_group_get_updated'] = expect(srv.call('GET', '%s/environment/%d' % (base, eid)), 200, 'environment')
    out['variable_group_update_id_mismatch'] = srv.call(
        'PUT', '%s/environment/%d' % (base, eid), dict(group, id=eid + 1000, secrets=[]))
    out['variable_group_refs_unused'] = expect(srv.call('GET', '%s/environment/%d/refs' % (base, eid)), 200, 'environment refs')
    out['variable_group_delete'] = expect(srv.call('DELETE', '%s/environment/%d' % (base, eid)), 204, 'delete environment')

    out['repository_update'] = expect(srv.call('PUT', '%s/repositories/%d' % (base, rid), {
        'id': rid, 'project_id': pid, 'name': 'ansible', 'git_url': 'git@github.com:example/ansible.git',
        'git_branch': 'develop', 'ssh_key_id': kid}), 204, 'update repository')
    out['repositories_one_updated'] = expect(srv.call('GET', base + '/repositories'), 200, 'repositories')
    out['repository_refs_unused'] = expect(srv.call('GET', '%s/repositories/%d/refs' % (base, rid)), 200, 'repository refs')
    out['repository_delete'] = expect(srv.call('DELETE', '%s/repositories/%d' % (base, rid)), 204, 'delete repository')
    out['key_delete'] = expect(srv.call('DELETE', '%s/keys/%d' % (base, kid)), 204, 'delete key')

    out['project_delete'] = expect(srv.call('DELETE', '/project/%d' % pid), 204, 'delete project')
    # What a task that names a project by an id that is gone gets. Not checked: the answer is the recording.
    out['project_get_deleted'] = srv.call('GET', '/project/%d' % pid)
    out['logout'] = expect(srv.call('POST', '/auth/logout'), 204, 'logout')
    # Log in again, so areas recorded after this one keep a session.
    expect(srv.call('POST', '/auth/login', {'auth': srv.username, 'password': srv.password}), 204, 'login')


TEAM_PROJECT = 'fixtures-team'
TEAM_USERS = ('tm-fixture-a', 'tm-fixture-b')


def sweep_team(srv):
    """Delete project fixtures-team and the two users of the team area."""
    delete_projects(srv, TEAM_PROJECT)
    for user in expect(srv.call('GET', '/users'), 200, 'users')['body'] or []:
        if user['username'] in TEAM_USERS:
            expect(srv.call('DELETE', '/users/%d' % user['id']), 204, 'delete leftover user %s' % user['username'])


def record_team(srv, out):
    """Project membership, in project fixtures-team with two throwaway users."""
    project_name = TEAM_PROJECT
    usernames = TEAM_USERS
    users = {}
    for name in usernames:
        users[name] = expect(srv.call('POST', '/users', {
            'username': name, 'name': name.upper(), 'email': name + '@example.com',
            'password': 'not-a-real-password-1', 'admin': False}), 201, 'create user')['body']
    out['team_user_current'] = expect(srv.call('GET', '/user'), 200, 'current user')
    # The search matches other people's users too, and /projects lists every project; keep only this area's.
    def own_user(user):
        return user['username'] in usernames

    out['team_users_search'] = keep(expect(srv.call('GET', '/users?s=tm-fixture-a'), 200, 'search users'), own_user)
    out['team_users_search_prefix'] = keep(expect(srv.call('GET', '/users?s=tm-fixture'), 200, 'search users by prefix'),
                                           own_user)
    project = expect(srv.call('POST', '/projects', {'name': project_name}), 201, 'create project')['body']
    pid = project['id']
    base = '/project/%d/users' % pid
    out['team_projects_list'] = keep(expect(srv.call('GET', '/projects'), 200, 'projects'),
                                     lambda p: p['id'] == pid)
    out['team_members_initial'] = expect(srv.call('GET', base), 200, 'members')
    a, b = users['tm-fixture-a']['id'], users['tm-fixture-b']['id']
    out['team_member_add'] = expect(srv.call('POST', base, {'user_id': a, 'role': 'manager'}), 204, 'add member')
    out['team_member_add_duplicate'] = srv.call('POST', base, {'user_id': a, 'role': 'manager'})
    out['team_member_add_bad_role'] = srv.call('POST', base, {'user_id': b, 'role': 'nope'})
    out['team_members_two'] = expect(srv.call('GET', base), 200, 'members')
    out['team_member_update'] = expect(srv.call('PUT', '%s/%d' % (base, a), {'role': 'owner'}), 204, 'update member')
    out['team_members_updated'] = expect(srv.call('GET', base), 200, 'members')
    out['team_member_remove'] = expect(srv.call('DELETE', '%s/%d' % (base, a)), 204, 'remove member')
    out['team_members_after_remove'] = expect(srv.call('GET', base), 200, 'members')


# Placeholder for the one-time registration token Semaphore hands out: the
# real one is a live credential until it expires, so it is never written.
RECORDED_TOKEN = 'smrs_recorded-registration-token'


RUNNER_PREFIX = 'rn-fixture'
RUNNER_PROJECT = 'rn-fixtures'


def sweep_runner(srv):
    """Delete the runners named rn-fixture* and project rn-fixtures."""
    for runner in expect(srv.call('GET', '/runners'), 200, 'runners')['body'] or []:
        if runner['name'].startswith(RUNNER_PREFIX):
            expect(srv.call('DELETE', '/runners/%d' % runner['id']), 204, 'delete leftover runner %s' % runner['name'])
    delete_projects(srv, RUNNER_PROJECT)


def record_runner(srv, out):
    """Global runners (and what a Community server says about project runners).

    Runners are global objects, so this only touches runners named rn-fixture*
    and a project named rn-fixtures, and works next to anything else.
    """
    out['runner_create'] = expect(srv.call('POST', '/runners', {
        'name': 'rn-fixture', 'max_parallel_tasks': 2, 'webhook': '', 'active': True, 'is_default': False,
        'tags': ['b', 'a']}), 201, 'create runner')
    rid = out['runner_create']['body']['id']
    listing = expect(srv.call('GET', '/runners'), 200, 'runners')
    # Other people's runners may be on the server; keep only this one.
    listing['body'] = [r for r in listing['body'] if r['id'] == rid]
    out['runner_list_one'] = listing
    out['runner_get'] = expect(srv.call('GET', '/runners/%d' % rid), 200, 'runner')
    token = expect(srv.call('POST', '/runners/%d/registration-token' % rid), 200, 'registration token')
    if not token['body']['registration_token'].startswith('smrs_'):
        sys.exit('registration token has an unexpected shape')
    srv.secrets.append(token['body']['registration_token'])
    token['body']['registration_token'] = RECORDED_TOKEN
    out['runner_registration_token'] = token
    runner = dict(out['runner_get']['body'])
    out['runner_update'] = expect(srv.call('PUT', '/runners/%d' % rid, dict(runner, webhook='https://hooks.example.com/r')),
                                  204, 'update runner')
    listing = expect(srv.call('GET', '/runners'), 200, 'runners')
    listing['body'] = [r for r in listing['body'] if r['id'] == rid]
    out['runner_list_one_updated'] = listing
    out['runner_delete'] = expect(srv.call('DELETE', '/runners/%d' % rid), 204, 'delete runner')
    out['runner_get_deleted'] = srv.call('GET', '/runners/%d' % rid)

    pid = expect(srv.call('POST', '/projects', {'name': RUNNER_PROJECT}), 201, 'create project')['body']['id']
    # Project runners are a Pro feature; a Community server answers 404.
    out['runner_project_list_community'] = srv.call('GET', '/project/%d/runners' % pid)
    out['runner_project_create_community'] = srv.call('POST', '/project/%d/runners' % pid, {
        'name': 'rn-fixture', 'project_id': pid})
    expect(srv.call('DELETE', '/project/%d' % pid), 204, 'delete project')


USER_PREFIX = 'us-fixture-'


def sweep_user(srv):
    """Delete the users named us-fixture-*, whichever run made them."""
    for user in expect(srv.call('GET', '/users'), 200, 'users')['body'] or []:
        if user['username'].startswith(USER_PREFIX):
            expect(srv.call('DELETE', '/users/%d' % user['id']), 204, 'delete leftover user %s' % user['username'])


def record_user(srv, out):
    """Global users: a local and an external one, created and deleted again.

    Works next to other users, who are left out of the recorded listings.
    The recorder never logs in as the users it creates, because Semaphore 2.18
    cannot delete a user who has a session.
    """
    stamp = str(os.getpid())
    login, ext = USER_PREFIX + stamp, USER_PREFIX + 'ext-' + stamp
    out['user_me'] = expect(srv.call('GET', '/user'), 200, 'current user')
    out['user_create'] = expect(srv.call('POST', '/users', {
        'username': login, 'name': 'Fixture', 'email': login + '@example.com', 'admin': False, 'alert': False,
        'external': False, 'password': 'not-a-real-password'}), 201, 'create user')
    uid = out['user_create']['body']['id']
    out['user_create_external'] = expect(srv.call('POST', '/users', {
        'username': ext, 'name': 'External', 'email': ext + '@example.com', 'external': True}), 201, 'create external user')
    xid = out['user_create_external']['body']['id']
    out['user_create_duplicate_email'] = srv.call('POST', '/users', {
        'username': login + '-dup', 'name': 'Dup', 'email': login + '@example.com', 'password': 'not-a-real-password'})
    # The two users above and the one the recorder is logged in as; nobody else's.
    mine = (uid, xid, out['user_me']['body']['id'])

    def own(listed):
        return listed['id'] in mine

    out['user_list'] = keep(expect(srv.call('GET', '/users'), 200, 'users'), own)
    user = dict(out['user_create']['body'])
    out['user_update'] = expect(srv.call('PUT', '/users/%d' % uid, dict(user, name='Fixture Team', alert=True)),
                                204, 'update user')
    out['user_list_updated'] = keep(expect(srv.call('GET', '/users'), 200, 'users'), own)
    out['user_password'] = expect(srv.call('POST', '/users/%d/password' % uid, {'password': 'not-a-real-password-2'}),
                                  204, 'set password')
    out['user_password_external'] = srv.call('POST', '/users/%d/password' % xid, {'password': 'not-a-real-password'})
    out['user_delete'] = expect(srv.call('DELETE', '/users/%d' % uid), 204, 'delete user')
    expect(srv.call('DELETE', '/users/%d' % xid), 204, 'delete external user')


TASK_PROJECT = 'fixtures-task'
# How long the slow template's task runs, in seconds: long enough to be seen
# running and to be stopped, short enough to wait for.
TASK_SECONDS = 6
TASK_FINAL = ('success', 'error', 'stopped')


def sweep_task(srv):
    """Delete project fixtures-task; its templates and tasks go with it."""
    delete_projects(srv, TASK_PROJECT)


def record_task(srv, out):
    """Starting, watching and stopping tasks, in project fixtures-task.

    The tasks run in the server's own container and need nothing from outside
    it: the repository is the local path /dev and the "playbook" of the bash
    templates is null, so a task runs `bash null` there, which does nothing
    and succeeds. A task that takes a while comes from a variable group that
    sets BASH_ENV for the process: bash expands that value before it reads
    the script, and the value is a command substitution that sleeps.
    """
    project = expect(srv.call('POST', '/projects', {'name': TASK_PROJECT}), 201, 'create project')['body']
    pid = project['id']
    base = '/project/%d' % pid
    out['task_projects_list'] = keep(expect(srv.call('GET', '/projects'), 200, 'projects'), lambda p: p['id'] == pid)

    kid = expect(srv.call('POST', base + '/keys', {'project_id': pid, 'name': 'tk-none', 'type': 'none'}),
                 201, 'create key')['body']['id']
    rid = expect(srv.call('POST', base + '/repositories', {
        'project_id': pid, 'name': 'tk-local', 'git_url': '/dev', 'git_branch': '', 'ssh_key_id': kid}),
        201, 'create repository')['body']['id']
    iid = expect(srv.call('POST', base + '/inventory', {
        'project_id': pid, 'name': 'tk-inventory', 'type': 'static', 'inventory': 'localhost', 'ssh_key_id': kid}),
        201, 'create inventory')['body']['id']

    def group(name, env):
        return expect(srv.call('POST', base + '/environment', {
            'project_id': pid, 'name': name, 'json': '{}', 'env': json.dumps(env)}), 201, 'create variable group')['body']['id']

    plain = group('tk-plain', {})
    slow = group('tk-slow', {'BASH_ENV': '$(echo "tk-slow started" >&2; sleep %d; echo "tk-slow done" >&2)' % TASK_SECONDS})

    def template(name, group_id, **more):
        body = dict({'project_id': pid, 'name': name, 'app': 'bash', 'playbook': 'null', 'repository_id': rid,
                     'inventory_id': iid, 'environment_id': group_id, 'type': ''}, **more)
        return expect(srv.call('POST', base + '/templates', body), 201, 'create template %s' % name)['body']['id']

    quick_id = template('tk-quick', plain)
    slow_id = template('tk-slow', slow, allow_override_args_in_task=True)
    fail_id = template('tk-fail', plain, playbook='tk-missing.sh')
    build_id = template('tk-build', plain, type='build', start_version='1.0.0')
    deploy_id = template('tk-deploy', plain, type='deploy', build_template_id=build_id)
    out['task_templates'] = expect(srv.call('GET', base + '/templates'), 200, 'templates')

    def watch(task_id, wanted, what):
        """The task's GET answer once its status is one of `wanted`."""
        seen = None
        for dummy in range(200):
            seen = expect(srv.call('GET', '%s/tasks/%d' % (base, task_id)), 200, 'task %s' % what)
            status = seen['body']['status']
            if status in wanted:
                return seen
            if status in TASK_FINAL:
                break
            time.sleep(0.2)
        sys.exit('task %s: waited for %s, the task is %s. Record this area again.'
                 % (what, ' or '.join(wanted), seen['body']['status']))

    def output(task_id, what):
        # The last lines reach the output a moment after the task's final status.
        time.sleep(2)
        return expect(srv.call('GET', '%s/tasks/%d/output' % (base, task_id)), 200, 'output %s' % what)

    # A task from start to success, with what a task may set for itself.
    out['task_start'] = expect(srv.call('POST', base + '/tasks', {
        'template_id': slow_id, 'message': 'recorded', 'environment': json.dumps({'who': 'world'}),
        'arguments': json.dumps(['--flag'])}), 201, 'start task')
    first = out['task_start']['body']['id']
    out['task_get_waiting'] = watch(first, ('waiting',), 'right after its start')
    out['task_get_running'] = watch(first, ('running',), 'while it runs')
    out['task_output_running'] = expect(srv.call('GET', '%s/tasks/%d/output' % (base, first)), 200, 'output while running')
    out['task_get_success'] = watch(first, ('success',), 'at its end')
    out['task_output'] = output(first, 'of the finished task')

    # A task that fails: its script is not there.
    out['task_start_failing'] = expect(srv.call('POST', base + '/tasks', {'template_id': fail_id}), 201, 'start failing task')
    failing = out['task_start_failing']['body']['id']
    out['task_get_error'] = watch(failing, ('error',), 'that fails')
    out['task_output_error'] = output(failing, 'of the failed task')

    # A task stopped while it runs.
    out['task_start_to_stop'] = expect(srv.call('POST', base + '/tasks', {'template_id': slow_id}), 201, 'start task to stop')
    stopping = out['task_start_to_stop']['body']['id']
    watch(stopping, ('running',), 'to stop')
    out['task_stop'] = expect(srv.call('POST', '%s/tasks/%d/stop' % (base, stopping), {'force': False}), 204, 'stop task')
    out['task_get_stopped'] = watch(stopping, ('stopped',), 'after the stop')
    out['task_output_stopped'] = output(stopping, 'of the stopped task')

    # A build, and the deploy of that build.
    out['task_start_build'] = expect(srv.call('POST', base + '/tasks', {'template_id': build_id}), 201, 'start build')
    build = out['task_start_build']['body']['id']
    out['task_get_build_success'] = watch(build, ('success',), 'build')
    out['task_start_deploy'] = expect(srv.call('POST', base + '/tasks', {
        'template_id': deploy_id, 'build_task_id': build}), 201, 'start deploy')
    out['task_get_deploy_success'] = watch(out['task_start_deploy']['body']['id'], ('success',), 'deploy')

    # A task that finishes at once.
    out['task_start_quick'] = expect(srv.call('POST', base + '/tasks', {'template_id': quick_id}), 201, 'start quick task')
    out['task_get_quick_success'] = watch(out['task_start_quick']['body']['id'], ('success',), 'quick')

    # Lists, newest first.
    out['task_list_last'] = expect(srv.call('GET', base + '/tasks/last?limit=3'), 200, 'last tasks')
    out['task_list_template'] = expect(srv.call('GET', '%s/templates/%d/tasks/last?limit=20' % (base, slow_id)),
                                       200, 'tasks of a template')

    # What the server refuses.
    out['task_start_unknown_template'] = srv.call('POST', base + '/tasks', {'template_id': slow_id + 100000})
    out['task_start_environment_object'] = srv.call('POST', base + '/tasks', {
        'template_id': slow_id, 'environment': {'who': 'world'}})
    missing = first + 100000
    out['task_get_missing'] = srv.call('GET', '%s/tasks/%d' % (base, missing))
    out['task_output_missing'] = srv.call('GET', '%s/tasks/%d/output' % (base, missing))
    out['task_stop_missing'] = srv.call('POST', '%s/tasks/%d/stop' % (base, missing), {'force': False})


# -- project backup and restore ------------------------------------------------

BACKUP_PROJECT = 'bk-fixtures'
BACKUP_PROJECTS = (BACKUP_PROJECT, 'bk-fixtures-restored', 'bk-fixtures-broken', 'bk-fixtures-partial')


def sweep_backup(srv):
    """Delete the projects named bk-fixtures*."""
    delete_projects(srv, *BACKUP_PROJECTS)


def record_backup(srv, out):
    """A project's backup, and what restoring it answers.

    Works next to anything else: it only touches projects named bk-fixtures*.
    A backup holds no secrets and no ids, so it is recorded as it comes.
    """
    def own(project):
        return project['name'] in BACKUP_PROJECTS

    pid = expect(srv.call('POST', '/projects', {'name': BACKUP_PROJECT, 'alert': False, 'max_parallel_tasks': 2}),
                 201, 'create project')['body']['id']
    base = '/project/%d' % pid
    kid = expect(srv.call('POST', base + '/keys', {
        'project_id': pid, 'name': 'deploy', 'type': 'ssh',
        'ssh': {'login': 'git', 'passphrase': '', 'private_key': FAKE_PRIVATE_KEY}}), 201, 'create key')['body']['id']
    rid = expect(srv.call('POST', base + '/repositories', {
        'project_id': pid, 'name': 'ansible', 'git_url': 'git@github.com:example/ansible.git',
        'git_branch': 'main', 'ssh_key_id': kid}), 201, 'create repository')['body']['id']
    iid = expect(srv.call('POST', base + '/inventory', {
        'project_id': pid, 'name': 'hosts', 'type': 'static', 'inventory': 'localhost',
        'ssh_key_id': kid}), 201, 'create inventory')['body']['id']
    eid = expect(srv.call('POST', base + '/environment', {
        'project_id': pid, 'name': 'vars', 'json': '{}', 'env': '{"TZ": "UTC"}',
        'secrets': [{'name': 'API_KEY', 'secret': 'not-a-real-secret', 'type': 'var', 'operation': 'create'}]}),
        201, 'create environment')['body']['id']
    tid = expect(srv.call('POST', base + '/templates', {
        'project_id': pid, 'name': 'site', 'app': 'ansible', 'playbook': 'site.yml', 'repository_id': rid,
        'inventory_id': iid, 'environment_id': eid, 'type': ''}), 201, 'create template')['body']['id']
    expect(srv.call('POST', base + '/schedules', {
        'project_id': pid, 'template_id': tid, 'name': 'nightly', 'cron_format': '0 3 * * *', 'active': True}),
        201, 'create schedule')

    out['backup_projects'] = keep(expect(srv.call('GET', '/projects'), 200, 'projects'), own)
    out['backup_project_get'] = expect(srv.call('GET', base), 200, 'project')
    out['backup_get'] = expect(srv.call('GET', base + '/backup'), 200, 'backup')
    backup = out['backup_get']['body']

    # Restoring creates a project, and refuses the name of one that exists.
    out['backup_restore_exists'] = expect(srv.call('POST', '/projects/restore', backup), 400, 'restore, same name')
    renamed = json.loads(json.dumps(backup))
    renamed['meta']['name'] = 'bk-fixtures-restored'
    out['backup_restore'] = expect(srv.call('POST', '/projects/restore', renamed), 200, 'restore')
    out['backup_projects_restored'] = keep(expect(srv.call('GET', '/projects'), 200, 'projects'), own)
    new = '/project/%d' % out['backup_restore']['body']['id']
    # What a restored project has: keys without their secrets, and no secret variables.
    out['backup_restored_keys'] = expect(srv.call('GET', new + '/keys'), 200, 'restored keys')
    out['backup_restored_environments'] = expect(srv.call('GET', new + '/environment'), 200, 'restored environments')
    expect(srv.call('DELETE', new), 204, 'delete restored project')

    # A reference to a name that is not in the backup is found before anything is created ...
    broken = json.loads(json.dumps(backup))
    broken['meta']['name'] = 'bk-fixtures-broken'
    broken['templates'][0]['repository'] = 'no-such-repository'
    out['backup_restore_broken'] = expect(srv.call('POST', '/projects/restore', broken), 400, 'restore, broken')
    out['backup_projects_after_broken'] = keep(expect(srv.call('GET', '/projects'), 200, 'projects'), own)
    # ... but not every one is: a schedule's template is only looked up after the project was created.
    partial = {'meta': {'name': 'bk-fixtures-partial'},
               'schedules': [{'name': 'nightly', 'template': 'no-such-template', 'cron_format': '0 3 * * *'}]}
    out['backup_restore_partial'] = expect(srv.call('POST', '/projects/restore', partial), 400, 'restore, partial')
    out['backup_projects_after_partial'] = keep(expect(srv.call('GET', '/projects'), 200, 'projects'), own)


# -- the activity log ----------------------------------------------------------

EVENT_PROJECT = 'ev-fixtures'


def sweep_event(srv):
    """Delete project ev-fixtures."""
    delete_projects(srv, EVENT_PROJECT)


def record_event(srv, out):
    """Events of a project, and the same ones in the lists across projects.

    Works next to anything else: it keeps only the events of project
    ev-fixtures. They name the account the recorder logs in with.
    """
    pid = expect(srv.call('POST', '/projects', {'name': EVENT_PROJECT}), 201, 'create project')['body']['id']
    base = '/project/%d' % pid
    kid = expect(srv.call('POST', base + '/keys', {'project_id': pid, 'name': 'none', 'type': 'none'}),
                 201, 'create key')['body']['id']
    expect(srv.call('POST', base + '/repositories', {
        'project_id': pid, 'name': 'ansible', 'git_url': 'https://github.com/example/ansible.git',
        'git_branch': 'main', 'ssh_key_id': kid}), 201, 'create repository')
    expect(srv.call('PUT', base, {'id': pid, 'name': EVENT_PROJECT, 'alert': False, 'max_parallel_tasks': 1}),
           204, 'update project')

    def own(event):
        return event.get('project_id') == pid

    out['event_projects'] = keep(expect(srv.call('GET', '/projects'), 200, 'projects'),
                                 lambda project: project['name'] == EVENT_PROJECT)
    out['events_project_last'] = expect(srv.call('GET', base + '/events/last'), 200, 'project events')
    out['events_project'] = expect(srv.call('GET', base + '/events'), 200, 'project events')
    out['events_last'] = keep(expect(srv.call('GET', '/events/last'), 200, 'events'), own)
    out['events'] = keep(expect(srv.call('GET', '/events'), 200, 'events'), own)


# -- API tokens ----------------------------------------------------------------

TOKEN_PREFIX = 'tk-fixture'
# Written in place of a token: Semaphore's own shape, and nothing a server ever made.
RECORDED_API_TOKEN = '%s-recorded-not-a-real-api-token-000000='


def sweep_token(srv):
    """Revoke the API tokens named tk-fixture* of the account the recorder logs in with."""
    for token in expect(srv.call('GET', '/user/tokens'), 200, 'tokens')['body'] or []:
        if (token.get('name') or '').startswith(TOKEN_PREFIX):
            expect(srv.call('DELETE', '/user/tokens/%s' % token['id']), 204, 'delete leftover token %s' % token['name'])


def record_token(srv, out):
    """The API tokens of the account the recorder logs in with.

    Works next to the account's other tokens: it keeps only those named
    tk-fixture*. A new token's answer is the token itself, and the list has
    the first eight characters of each; both are replaced before anything is
    written, the same stand-in start for the same token.
    """
    stand_ins = {}

    def masked(result):
        """The answer with every token of this run, whole or as its listed start, replaced."""
        def stand_in(value):
            start = stand_ins.setdefault(value[:8], 'tkfix%03d' % (len(stand_ins) + 1))
            return start if len(value) <= 8 else RECORDED_API_TOKEN % start
        body = result['body']
        if isinstance(body, list):
            body = [dict(token, id=stand_in(token['id'])) for token in body]
        elif isinstance(body, dict) and 'id' in body:
            body = dict(body, id=stand_in(body['id']))
        return dict(result, body=body)

    def own(token):
        return (token.get('name') or '').startswith(TOKEN_PREFIX)

    def listing():
        return masked(keep(expect(srv.call('GET', '/user/tokens'), 200, 'tokens'), own))

    out['tokens_none'] = listing()
    created = expect(srv.call('POST', '/user/tokens', {'name': TOKEN_PREFIX}), 201, 'create token')
    token = created['body']['id']
    srv.secrets.append(token)
    out['token_create'] = masked(created)
    out['tokens_one'] = listing()
    # The token works, and the start the list shows of it does not.
    expect(srv.call('GET', '/user', token=token), 200, 'the token is taken')
    expiring = expect(srv.call('POST', '/user/tokens', {
        'name': TOKEN_PREFIX + '-expiring', 'expires_at': '2099-01-01T00:00:00Z'}), 201, 'create expiring token')
    srv.secrets.append(expiring['body']['id'])
    out['token_create_expiring'] = masked(expiring)
    out['tokens_two'] = listing()
    out['token_create_past'] = expect(srv.call('POST', '/user/tokens', {
        'name': TOKEN_PREFIX + '-past', 'expires_at': '2001-01-01T00:00:00Z'}), 400, 'create token, past expiry')
    # Deleting goes by the start of a token, and answers the same when no token starts that way.
    out['token_delete'] = expect(srv.call('DELETE', '/user/tokens/%s' % token[:8]), 204, 'delete token')
    out['token_delete_unknown'] = expect(srv.call('DELETE', '/user/tokens/%s' % token[:8]), 204, 'delete it again')
    out['tokens_after_delete'] = listing()
    expect(srv.call('DELETE', '/user/tokens/%s' % expiring['body']['id'][:8]), 204, 'delete expiring token')


# Area name -> recorder. Each writes fixtures/<major.minor>/<area>.json.
AREAS = {
    'backup': record_backup,
    'core': record_core,
    'event': record_event,
    'team': record_team,
    'token': record_token,
    'runner': record_runner,
    'task': record_task,
    'user': record_user,
}
# Area name -> what takes the area's own objects off the server (see run_area).
SWEEPS = {
    'backup': sweep_backup,
    'core': sweep_core,
    'event': sweep_event,
    'team': sweep_team,
    'token': sweep_token,
    'runner': sweep_runner,
    'task': sweep_task,
    'user': sweep_user,
}


def main():
    url, areas, allow_remote = parse_args(sys.argv, AREAS)
    require_throwaway(url, allow_remote)
    password = os.environ.get('SEMAPHORE_PASSWORD')
    if not password:
        sys.exit('set SEMAPHORE_PASSWORD to the admin password')
    srv = Server(url)
    srv.username = os.environ.get('SEMAPHORE_USERNAME', 'admin')
    srv.password = password
    srv.secrets.append(password)

    bad_login = expect(srv.call('POST', '/auth/login', {'auth': srv.username, 'password': 'wrong'}), 401, 'bad login')
    login = expect(srv.call('POST', '/auth/login', {'auth': srv.username, 'password': password}), 204, 'login')
    version = expect(srv.call('GET', '/info'), 200, 'info')['body']['version']
    minor = re.match(r'^v?(\d+\.\d+)', version).group(1)

    for area in areas:
        out = {}
        if area == 'core':
            out.update(login_bad_password=bad_login, login=login)
        run_area(area, AREAS[area], SWEEPS[area], srv, out)
        path = os.path.normpath(os.path.join(FIXTURES, minor, '%s.json' % area))
        write_fixture(path, version, out, srv.secrets, placeholders=(RECORDED_TOKEN,))


if __name__ == '__main__':
    main()
