# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Tests for what keeps the fixture recorders from publishing a real server's data,
and from leaving their objects behind on it.

No server is needed. Run them with `make tools-test`.
"""

import glob
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import record_harbor_fixtures as harbor  # noqa: E402
import record_semaphoreui_fixtures as semaphore  # noqa: E402
import recorder_common as common  # noqa: E402

AREAS = dict(core=None, user=None)


def resolver(*addresses):
    return lambda host, port: [(None, None, None, '', (address, 0)) for address in addresses]


def no_such_host(host, port):
    raise OSError('no such host')


class ParseArgs(unittest.TestCase):
    def test_url_alone_records_every_area(self):
        self.assertEqual(common.parse_args(['rec', 'http://127.0.0.1:3000'], AREAS),
                         ('http://127.0.0.1:3000', ['core', 'user'], False))

    def test_flag_is_accepted_anywhere(self):
        for argv in (['rec', '--allow-remote', 'http://h', 'user'], ['rec', 'http://h', 'user', '--allow-remote']):
            self.assertEqual(common.parse_args(argv, AREAS), ('http://h', ['user'], True))

    def test_usage_errors_exit(self):
        for argv in (['rec'], ['rec', '--allow-remote'], ['rec', '--help'], ['rec', 'http://h', 'nope']):
            with self.assertRaises(SystemExit):
                common.parse_args(argv, AREAS)


class Guard(unittest.TestCase):
    def test_loopback_addresses(self):
        for url in ('http://127.0.0.1:3019', 'http://127.8.9.1/api', 'https://[::1]:8443'):
            self.assertTrue(common.is_loopback(url, no_such_host), url)

    def test_other_addresses(self):
        for url in ('http://10.0.0.5:3000', 'http://192.168.1.10', 'http://0.0.0.0:3000', 'https://[2001:db8::1]', 'not a url'):
            self.assertFalse(common.is_loopback(url, no_such_host), url)

    def test_names_count_only_when_every_address_is_loopback(self):
        self.assertTrue(common.is_loopback('http://localhost:3000', resolver('127.0.0.1', '::1')))
        self.assertFalse(common.is_loopback('http://semaphore.example.com', resolver('10.0.0.5')))
        self.assertFalse(common.is_loopback('http://mixed.example.com', resolver('127.0.0.1', '10.0.0.5')))
        self.assertFalse(common.is_loopback('http://gone.example.com', no_such_host))
        self.assertFalse(common.is_loopback('http://empty.example.com', resolver()))

    def test_remote_server_is_refused_without_the_flag(self):
        with self.assertRaises(SystemExit) as refused:
            common.require_throwaway('https://harbor.example.com', False, resolver('10.0.0.5'))
        self.assertIn('--allow-remote', str(refused.exception))
        common.require_throwaway('https://harbor.example.com', True, resolver('10.0.0.5'))
        common.require_throwaway('http://127.0.0.1:8015', False, no_such_host)


class Keep(unittest.TestCase):
    def test_drops_other_items_and_corrects_the_total(self):
        listing = dict(status=200, headers={'x-total-count': '3'},
                       body=[dict(name='library'), dict(name='payroll'), dict(name='fixtures-core')])
        kept = common.keep(listing, harbor.named('fixtures-core', harbor.BUILT_IN_PROJECT))
        self.assertEqual([p['name'] for p in kept['body']], ['library', 'fixtures-core'])
        self.assertEqual(kept['headers'], {'x-total-count': '2'})
        self.assertEqual(len(listing['body']), 3)
        self.assertEqual(listing['headers'], {'x-total-count': '3'})

    def test_leaves_responses_without_a_total_or_a_list_alone(self):
        self.assertEqual(common.keep(dict(status=200, body=[dict(name='rr-fixtures-a'), dict(name='prod')]),
                                     harbor.named_like('rr-fixtures')),
                         dict(status=200, body=[dict(name='rr-fixtures-a')]))
        error = dict(status=403, body=dict(errors=[]), headers={})
        self.assertIs(common.keep(error, lambda item: False), error)
        self.assertEqual(common.keep(dict(status=200, body=None), lambda item: True), dict(status=200, body=None))


class SiteSettings(unittest.TestCase):
    def test_text_goes_back_to_the_default_and_the_rest_stays(self):
        config = dict(status=200, headers={}, body=dict(
            ldap_url=dict(editable=True, value='ldaps://ldap.corp.example.com'),
            ldap_search_dn=dict(editable=True, value='cn=harbor,dc=corp'),
            ldap_uid=dict(editable=True, value='sAMAccountName'),
            ldap_timeout=dict(editable=True, value=9),
            oidc_client_id=dict(editable=True, value='harbor-prod'),
            oidc_verify_cert=dict(editable=True, value=False),
            oidc_extra_redirect_parms=dict(editable=True, value='{"hd": "corp"}'),
            uaa_client_secret=dict(editable=True, value='hunter2'),
            http_authproxy_endpoint=dict(editable=True, value='https://proxy.corp'),
            audit_log_forward_endpoint=dict(editable=True, value='syslog.corp:514'),
            robot_name_prefix=dict(editable=True, value='robot$'),
            banner_message=dict(editable=True, value='fixtures-system'),
            scan_all_policy=dict()))
        body = harbor.without_site_settings(config)['body']
        self.assertEqual(dict((k, v.get('value')) for k, v in body.items()), dict(
            ldap_url='', ldap_search_dn='', ldap_uid='cn', ldap_timeout=9, oidc_client_id='', oidc_verify_cert=False,
            oidc_extra_redirect_parms='{}', uaa_client_secret='', http_authproxy_endpoint='',
            audit_log_forward_endpoint='', robot_name_prefix='robot$', banner_message='fixtures-system',
            scan_all_policy=None))
        self.assertEqual(config['body']['ldap_url']['value'], 'ldaps://ldap.corp.example.com')


class SecretScan(unittest.TestCase):
    def test_clean_recording(self):
        responses = dict(
            token=dict(status=200, body=dict(registration_token=semaphore.RECORDED_TOKEN)),
            robot=dict(status=201, body=dict(secret=harbor.RECORDED_SECRET, name='robot$x')),
            registry=dict(status=200, body=dict(credential=dict(access_key='admin', access_secret='*****'))),
            webhook=dict(status=200, body=dict(targets=[dict(auth_header='Bearer not-a-real-token')])),
            group=dict(status=200, body=dict(secrets=[dict(name='TOKEN', secret='')], password=None)),
            deleted=dict(status=204, body=None))
        self.assertEqual(common.find_secrets(responses, ['S3cret-admin-pw'], (semaphore.RECORDED_TOKEN, harbor.RECORDED_SECRET),
                                             harbor.SECRET_KEY), [])

    def test_known_secret_is_found_anywhere_and_never_quoted(self):
        found = common.find_secrets(dict(
            a=dict(status=200, body=[dict(note='login with S3cret-admin-pw')]),
            b=dict(status=200, body={'S3cret-admin-pw': 1}),
            c=dict(status=200, body='plain text S3cret-admin-pw')), ['S3cret-admin-pw', ''])
        self.assertEqual([line.split(':')[0] for line in found], ['a', 'b', 'c'])
        self.assertNotIn('S3cret-admin-pw', ''.join(found))

    def test_credential_shapes(self):
        found = common.find_secrets(dict(
            key=dict(body=dict(note='-----BEGIN OPENSSH PRIVATE KEY-----\nabc')),
            jwt=dict(body=dict(note='eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.c2lnbmF0dXJl')),
            runner=dict(body=dict(note='smrs_AbCdEf0123456789'))))
        self.assertEqual(found, ['jwt: holds a JSON Web Token', 'key: holds a private key',
                                 'runner: holds a Semaphore runner token'])

    def test_value_under_a_secret_key(self):
        responses = dict(robot=dict(body=dict(secret='Xy7generated')),
                         webhook=dict(body=dict(targets=[dict(auth_header='Bearer abc')])),
                         integration=dict(body=dict(auth_header='X-Token')))
        self.assertEqual(common.find_secrets(responses), ['robot: has a value under "secret"'])
        self.assertEqual(common.find_secrets(responses, secret_key=harbor.SECRET_KEY),
                         ['integration: has a value under "auth_header"', 'robot: has a value under "secret"',
                          'webhook: has a value under "auth_header"'])

    def test_committed_fixtures_pass(self):
        for recorder, placeholders, key in ((semaphore, (semaphore.RECORDED_TOKEN,), common.SECRET_KEY),
                                            (harbor, (harbor.RECORDED_SECRET,), harbor.SECRET_KEY)):
            paths = sorted(glob.glob(os.path.join(recorder.FIXTURES, '*', '*.json')))
            self.assertTrue(paths)
            for path in paths:
                with open(path) as f:
                    self.assertEqual(common.find_secrets(json.load(f)['responses'], (), placeholders, key), [], path)


class WriteFixture(unittest.TestCase):
    def test_writes_a_clean_recording_and_refuses_a_dirty_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, '2.19', 'user.json')
            common.write_fixture(path, 'v2.19.12', dict(user_me=dict(status=200, body=dict(username='admin'))), ['pw-9f2c'])
            with open(path) as f:
                self.assertEqual(json.load(f), dict(recorded_from='v2.19.12',
                                                    responses=dict(user_me=dict(status=200, body=dict(username='admin')))))
            dirty = os.path.join(tmp, '2.19', 'core.json')
            with self.assertRaises(SystemExit):
                common.write_fixture(dirty, 'v2.19.12', dict(x=dict(status=200, body=dict(note='pw-9f2c'))), ['pw-9f2c'])
            self.assertFalse(os.path.exists(dirty))


class RunArea(unittest.TestCase):
    def setUp(self):
        self.steps = []

    def sweep(self, srv):
        self.steps.append('sweep')

    def record(self, srv, out):
        self.steps.append('record')
        out['x'] = 1

    def failing_record(self, srv, out):
        self.steps.append('record')
        sys.exit('recording failed')

    def test_sweeps_before_and_after(self):
        out = {}
        common.run_area('core', self.record, self.sweep, None, out)
        self.assertEqual(self.steps, ['sweep', 'record', 'sweep'])
        self.assertEqual(out, dict(x=1))

    def test_sweeps_after_a_failed_recording_and_reports_that_failure(self):
        for error in (SystemExit('recording failed'), KeyError('id'), KeyboardInterrupt()):
            self.steps = []

            def record(srv, out, error=error):
                self.steps.append('record')
                raise error

            with self.assertRaises(type(error)) as raised:
                common.run_area('core', record, self.sweep, None, {})
            self.assertIs(raised.exception, error)
            self.assertEqual(self.steps, ['sweep', 'record', 'sweep'])

    def test_a_sweep_that_fails_after_a_failed_recording_does_not_hide_it(self):
        def sweep(srv):
            self.steps.append('sweep')
            if len(self.steps) > 1:
                sys.exit('sweep failed')

        with mock.patch('sys.stderr') as stderr:
            with self.assertRaises(SystemExit) as raised:
                common.run_area('core', self.failing_record, sweep, None, {})
        self.assertEqual(str(raised.exception), 'recording failed')
        self.assertEqual(self.steps, ['sweep', 'record', 'sweep'])
        self.assertIn('sweep failed', ''.join(call.args[0] for call in stderr.write.call_args_list))

    def test_a_failed_sweep_stops_the_area(self):
        def sweep(srv):
            sys.exit('leftovers that are not ours')

        with self.assertRaises(SystemExit):
            common.run_area('core', self.record, sweep, None, {})
        self.assertEqual(self.steps, [])

        def late(srv):
            self.steps.append('sweep')
            if self.steps.count('sweep') == 2:
                sys.exit('could not clean up')

        with self.assertRaises(SystemExit) as raised:
            common.run_area('core', self.record, late, None, {})
        self.assertEqual(str(raised.exception), 'could not clean up')

    def test_every_area_has_a_sweep(self):
        for recorder in (semaphore, harbor):
            self.assertEqual(sorted(recorder.SWEEPS), sorted(recorder.AREAS))


class FakeServer(object):
    """Answers GETs from a dict of path -> body and accepts every write; keeps what was called."""

    def __init__(self, gets, write_status):
        self.gets = gets
        self.write_status = write_status
        self.calls = []

    def call(self, method, path, body=None, **kwargs):
        self.calls.append((method, path) if body is None else (method, path, body))
        if method == 'GET':
            return dict(status=200, body=self.gets.get(path, []), headers={})
        return dict(status=self.write_status, body=None, headers={})

    def writes(self):
        return [call for call in self.calls if call[0] != 'GET']


class SemaphoreSweeps(unittest.TestCase):
    def server(self, **gets):
        return FakeServer(dict(('/' + path.replace('__', '/'), body) for path, body in gets.items()), 204)

    def test_runner_sweep_takes_only_its_own(self):
        srv = self.server(runners=[dict(id=1, name='rn-fixture'), dict(id=2, name='build-01'), dict(id=3, name='rn-fixture-x')],
                          projects=[dict(id=7, name='rn-fixtures'), dict(id=8, name='homelab'), dict(id=9, name='rn-fixtures-2')])
        semaphore.sweep_runner(srv)
        self.assertEqual(srv.writes(), [('DELETE', '/runners/1'), ('DELETE', '/runners/3'), ('DELETE', '/project/7')])

    def test_user_sweep_takes_only_its_own(self):
        srv = self.server(users=[dict(id=1, username='admin'), dict(id=2, username='us-fixture-4711'),
                                 dict(id=3, username='us-fixture-ext-4711'), dict(id=4, username='us-ops')])
        semaphore.sweep_user(srv)
        self.assertEqual(srv.writes(), [('DELETE', '/users/2'), ('DELETE', '/users/3')])

    def test_team_sweep_takes_only_its_own(self):
        srv = self.server(projects=[dict(id=7, name='fixtures-team'), dict(id=8, name='fixtures-team-old')],
                          users=[dict(id=1, username='tm-fixture-a'), dict(id=2, username='tm-fixture-c')])
        semaphore.sweep_team(srv)
        self.assertEqual(srv.writes(), [('DELETE', '/project/7'), ('DELETE', '/users/1')])

    def test_core_sweep_removes_what_an_earlier_recording_left(self):
        srv = self.server(projects=[dict(id=5, name='homelab')],
                          project__5__keys=[dict(id=1, name='deploy')],
                          project__5__repositories=[dict(id=2, name='ansible')],
                          project__5__templates=[dict(id=3, name='site'), dict(id=4, name='surveyed')])
        semaphore.sweep_core(srv)
        self.assertEqual(srv.writes(), [('DELETE', '/project/5/templates/3'), ('DELETE', '/project/5/templates/4'),
                                        ('DELETE', '/project/5/repositories/2'), ('DELETE', '/project/5/keys/1'),
                                        ('DELETE', '/project/5')])

    def test_core_sweep_refuses_a_homelab_that_is_someone_elses(self):
        srv = self.server(projects=[dict(id=5, name='homelab')],
                          project__5__keys=[dict(id=1, name='deploy'), dict(id=2, name='github-deploy-key')])
        with self.assertRaises(SystemExit) as refused:
            semaphore.sweep_core(srv)
        self.assertIn('github-deploy-key', str(refused.exception))
        self.assertEqual(srv.writes(), [])

    def test_core_sweep_leaves_other_projects_alone(self):
        srv = self.server(projects=[dict(id=5, name='payroll'), dict(id=6, name='homelab-2')])
        semaphore.sweep_core(srv)
        self.assertEqual(srv.calls, [('GET', '/projects')])

    def test_a_refused_delete_stops_the_sweep(self):
        srv = self.server(runners=[dict(id=1, name='rn-fixture')])
        srv.write_status = 400
        with self.assertRaises(SystemExit):
            semaphore.sweep_runner(srv)


class HarborSweeps(unittest.TestCase):
    def test_registry_sweep_takes_only_its_own_rules_first(self):
        srv = FakeServer({
            '/replication/policies?page=1&page_size=100': [dict(id=1, name='rr-fixtures-pull'), dict(id=2, name='mirror-prod')],
            '/registries?page=1&page_size=100': [dict(id=3, name='dockerhub'), dict(id=4, name='rr-fixtures-self'),
                                                 dict(id=5, name='rr-fixtures-auth')]}, 200)
        harbor.sweep_registry(srv)
        self.assertEqual(srv.writes(), [('DELETE', '/replication/policies/1'), ('DELETE', '/registries/4'),
                                        ('DELETE', '/registries/5')])

    def test_core_sweep_goes_by_the_exact_project_name(self):
        srv = FakeServer({
            '/projects?name=fixtures-core-proxy&page=1&page_size=100': [dict(project_id=9, name='fixtures-core-proxy')],
            '/projects?name=fixtures-core&page=1&page_size=100': [dict(project_id=9, name='fixtures-core-proxy'),
                                                                 dict(project_id=8, name='fixtures-core'),
                                                                 dict(project_id=7, name='my-fixtures-core')],
            '/registries?page=1&page_size=100': [dict(id=3, name='fixtures-core-hub'), dict(id=4, name='hub')]}, 200)
        harbor.sweep_core(srv)
        self.assertEqual(srv.writes(), [('DELETE', '/projects/9'), ('DELETE', '/projects/8'), ('DELETE', '/registries/3')])

    def test_tag_policy_sweep_takes_the_policy_and_the_rules_with_the_project(self):
        srv = FakeServer({
            '/projects?name=fixtures-tag-policy&page=1&page_size=100': [
                dict(project_id=6, name='fixtures-tag-policy', metadata=dict(retention_id='12'))],
            '/projects/6/immutabletagrules?page=1&page_size=100': [dict(id=26)]}, 200)
        harbor.sweep_tag_policy(srv)
        self.assertEqual(srv.writes(), [('DELETE', '/retentions/12'), ('DELETE', '/projects/6/immutabletagrules/26'),
                                        ('DELETE', '/projects/6')])

    def test_webhook_and_robot_sweeps_leave_a_server_without_leftovers_alone(self):
        for sweep in (harbor.sweep_webhook, harbor.sweep_robot, harbor.sweep_tag_policy, harbor.sweep_core,
                      harbor.sweep_registry):
            srv = FakeServer({}, 200)
            sweep(srv)
            self.assertEqual(srv.writes(), [], sweep.__name__)

    def system(self, banner, gc_cron, purge_cron):
        def schedule(cron):
            return dict(schedule=dict(type='Custom', cron=cron)) if cron else None
        return FakeServer({
            '/configurations': dict(banner_message=dict(value=banner), session_timeout=dict(value=45)),
            '/system/gc/schedule': schedule(gc_cron),
            '/system/purgeaudit/schedule': schedule(purge_cron)}, 200)

    def test_system_sweep_takes_back_only_what_the_area_sets(self):
        srv = self.system('fixtures-system', harbor.SYSTEM_GC_CRON, harbor.SYSTEM_PURGE_CRON)
        harbor.sweep_system(srv)
        self.assertEqual(srv.writes(), [
            ('PUT', '/configurations', dict(banner_message='', session_timeout=60)),
            ('PUT', '/system/gc/schedule', harbor.NO_GC_SCHEDULE),
            ('PUT', '/system/purgeaudit/schedule', harbor.NO_PURGE_SCHEDULE)])

    def test_system_sweep_leaves_a_sites_own_settings_and_schedules(self):
        srv = self.system('Maintenance on Sunday', '0 0 2 * * *', None)
        harbor.sweep_system(srv)
        self.assertEqual(srv.writes(), [])


class Response(object):
    status = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'{}'


class Timeout(unittest.TestCase):
    def test_harbor_requests_have_a_timeout(self):
        with mock.patch.object(harbor.urllib.request, 'urlopen', return_value=Response()) as urlopen:
            harbor.Server('http://127.0.0.1:8015', 'admin', 'pw').call('GET', '/systeminfo')
        self.assertEqual(urlopen.call_args.kwargs, dict(timeout=common.TIMEOUT))

    def test_semaphore_requests_have_a_timeout(self):
        srv = semaphore.Server('http://127.0.0.1:3019')
        srv.opener = mock.Mock()
        srv.opener.open.return_value = Response()
        srv.call('GET', '/info')
        self.assertEqual(srv.opener.open.call_args.kwargs, dict(timeout=common.TIMEOUT))

    def test_the_timeout_is_a_number_of_seconds(self):
        self.assertTrue(0 < common.TIMEOUT <= 120)


class LockedServer(harbor.Server):
    """A Harbor that answers the given statuses in turn, on a clock the test moves."""

    def __init__(self, *statuses, **kwargs):
        harbor.Server.__init__(self, 'http://127.0.0.1:8015', 'admin', 'right')
        self.statuses = list(statuses)
        self.body = kwargs.get('body', dict(harbor_version='v2.15.0'))
        self.now = 100.0
        self.sent = []
        self.slept = []
        self.clock = lambda: self.now
        self.sleep = self.wait

    def wait(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def send(self, method, path, body, password):
        self.sent.append((method, path, password))
        return dict(status=self.statuses.pop(0) if self.statuses else 200, body=self.body, headers={})


class LoginLock(unittest.TestCase):
    def test_a_wrong_password_request_is_sent_once_and_waited_out(self):
        srv = LockedServer(401, 200)
        self.assertEqual(srv.call('GET', '/configurations', password='wrong')['status'], 401)
        self.assertEqual((srv.sent, srv.slept), ([('GET', '/configurations', 'wrong')], []))
        srv.call('GET', '/projects')
        self.assertEqual(srv.slept, [harbor.LOCK_WAIT])
        self.assertEqual(srv.sent[1], ('GET', '/projects', 'right'))
        srv.call('GET', '/projects')
        self.assertEqual(srv.slept, [harbor.LOCK_WAIT])

    def test_only_the_rest_of_the_lock_is_waited(self):
        srv = LockedServer()
        srv.call('GET', '/systeminfo', password='wrong')
        srv.now += 1.5
        srv.call('GET', '/projects')
        self.assertEqual(srv.slept, [harbor.LOCK_WAIT - 1.5])

    def test_a_401_for_the_right_password_is_sent_again(self):
        srv = LockedServer(401, 401, 201)
        self.assertEqual(srv.call('POST', '/projects', dict(project_name='x'))['status'], 201)
        self.assertEqual(len(srv.sent), 3)
        self.assertEqual(srv.slept, [harbor.LOCK_WAIT, harbor.LOCK_WAIT])

    def test_a_401_that_stays_is_given_up_on(self):
        srv = LockedServer(*[401] * 50)
        self.assertEqual(srv.call('GET', '/projects')['status'], 401)
        self.assertEqual(len(srv.sent), harbor.LOCK_TRIES)

    def test_other_errors_are_not_sent_again(self):
        srv = LockedServer(409)
        self.assertEqual(srv.call('POST', '/projects', dict(project_name='x'))['status'], 409)
        self.assertEqual((len(srv.sent), srv.slept), (1, []))

    def test_an_anonymous_answer_is_not_taken_for_a_login(self):
        srv = LockedServer(body=dict(auth_mode='db_auth'))
        with self.assertRaises(SystemExit) as refused:
            srv.require_login()
        self.assertIn('harbor_version', str(refused.exception))
        self.assertEqual(len(srv.sent), harbor.LOCK_TRIES)

    def test_a_login_is_returned_as_recorded(self):
        srv = LockedServer()
        self.assertEqual(srv.require_login(), dict(status=200, body=dict(harbor_version='v2.15.0'), headers={}))
        self.assertEqual(len(srv.sent), 1)


if __name__ == '__main__':
    unittest.main()
