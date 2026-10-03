# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.configuration import (
    SETTING_TYPES,
    flat,
    is_secret,
    locked,
)


@pytest.mark.parametrize('key', [
    'uaa_client_secret', 'oidc_client_secret', 'ldap_search_password',
    'oidc_refresh_token', 'ldap_bind_password', 'smtp_passwd', 'registry_credential', 'jwt_private_key',
    'OIDC_CLIENT_SECRET_V2',
])
def test_secret_names(key):
    assert is_secret(key) is True


@pytest.mark.parametrize('key', [
    'robot_token_duration', 'token_expiration', 'http_authproxy_tokenreview_endpoint',
    'http_authproxy_server_certificate', 'oidc_verify_cert', 'scan_all_policy', 'some_new_setting',
])
def test_names_that_are_no_secret(key):
    assert is_secret(key) is False


def test_no_known_setting_is_taken_for_a_secret():
    assert [key for key in SETTING_TYPES if is_secret(key)] == []


def test_flat_takes_the_value_and_leaves_secrets_out():
    raw = dict(auth_mode=dict(value='db_auth', editable=False), session_timeout=dict(value=60, editable=True),
               scan_all_policy={}, uaa_client_secret=dict(value='s', editable=True),
               new_api_token=dict(value='t', editable=True), plain='text')
    assert flat(raw) == dict(auth_mode='db_auth', session_timeout=60, scan_all_policy=None, plain='text')
    assert flat(None) == {}


def test_locked_names_only_what_harbor_marks_as_not_editable():
    raw = dict(auth_mode=dict(value='db_auth', editable=False), session_timeout=dict(value=60, editable=True),
               read_only=dict(value=False, editable=False), scan_all_policy={}, plain='text')
    assert locked(raw, ['session_timeout', 'read_only', 'auth_mode', 'scan_all_policy', 'plain', 'absent']) == [
        'auth_mode', 'read_only']
    assert locked(None, ['auth_mode']) == []
