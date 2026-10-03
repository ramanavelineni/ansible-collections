# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Tests for what keeps the fixture recorders from publishing a real server's data.

No server is needed. Run them with `make tools-test`.
"""

import glob
import json
import os
import sys
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
