# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import registry, registry_info

SELF = dict(name='rr-fixtures-self', type='harbor', endpoint_url='http://proxy:8080/', insecure=True)


def rid(server, fixture='registry_create'):
    return int(server.fixtures[fixture]['headers']['location'].rsplit('/', 1)[-1])


def aid(server):
    return server.fixtures['registry_get_with_credential']['body']['id']


def test_create(server, run_module):
    server.route('GET', '/registries', 'registry_list_before')
    server.route('POST', '/registries', 'registry_create')
    server.route('GET', '/registries/%d' % rid(server), 'registry_get')
    result = run_module(registry.main, SELF)
    assert result['changed'] is True
    assert result['registry']['id'] == rid(server)
    assert result['registry']['status'] == 'healthy'
    assert server.calls('POST', '/registries')[0]['body'] == dict(
        name='rr-fixtures-self', type='harbor', url='http://proxy:8080', insecure=True, description='')


def test_create_with_credential(server, run_module):
    server.route('GET', '/registries', 'registry_list_before')
    server.route('POST', '/registries', 'registry_create')
    server.route('GET', '/registries/%d' % rid(server), 'registry_get_with_credential')
    result = run_module(registry.main, dict(SELF, access_key='admin', access_secret='t0p-secret'))
    assert result['secret_updated'] is True
    assert server.calls('POST', '/registries')[0]['body']['credential'] == dict(
        type='basic', access_key='admin', access_secret='t0p-secret')
    assert 't0p-secret' not in json.dumps(result)


def test_create_needs_type_and_url(server, run_module):
    server.route('GET', '/registries', 'registry_list_before')
    result = run_module(registry.main, dict(name='rr-fixtures-new'))
    assert result['failed'] is True
    assert 'type, endpoint_url' in result['msg']


def test_create_check_mode(server, run_module):
    server.route('GET', '/registries', 'registry_list_before')
    result = run_module(registry.main, SELF, check_mode=True)
    assert result['changed'] is True
    assert result['registry']['id'] is None
    assert server.calls('POST') == []


def test_unhealthy_endpoint_reported(server, run_module):
    server.route('GET', '/registries', 'registry_list_before')
    server.route('POST', '/registries', 'registry_create_unhealthy')
    result = run_module(registry.main, dict(name='rr-fixtures-dummy', type='docker-registry',
                                            endpoint_url='http://rr-nonexistent.invalid'))
    assert result['failed'] is True
    assert 'the registry is unhealthy' in result['msg']


def test_no_change_with_trailing_slash(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    result = run_module(registry.main, SELF)
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_update_sends_only_changed_fields(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/registries/%d' % rid(server), 'registry_update')
    result = run_module(registry.main, dict(name='rr-fixtures-self', description='updated'))
    assert result['changed'] is True
    assert result['diff']['before']['description'] == ''
    assert server.calls('PUT')[0]['body'] == dict(description='updated')


def test_update_check_mode(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    result = run_module(registry.main, dict(name='rr-fixtures-self', description='updated'), check_mode=True)
    assert result['changed'] is True
    assert server.calls('PUT') == []


def test_type_cannot_change(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    result = run_module(registry.main, dict(name='rr-fixtures-self', type='docker-hub'))
    assert result['failed'] is True
    assert 'cannot change the type' in result['msg']
    assert server.calls('PUT') == []


def test_secret_always_resent(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/registries/%d' % aid(server), 'registry_update')
    result = run_module(registry.main, dict(name='rr-fixtures-auth', access_key='admin', access_secret='s'))
    assert result['changed'] is True and result['secret_updated'] is True
    assert server.calls('PUT')[0]['body'] == dict(access_secret='s')


def test_secret_on_create_leaves_it(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    result = run_module(registry.main, dict(name='rr-fixtures-auth', access_key='admin', access_secret='s',
                                            update_secret='on_create'))
    assert result['changed'] is False and result['secret_updated'] is False


def test_rejected_secret_reported(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/registries/%d' % aid(server), 'registry_update_bad_secret')
    result = run_module(registry.main, dict(name='rr-fixtures-auth', access_secret='wrong-one'))
    assert result['failed'] is True
    assert 'unhealthy' in result['msg']
    assert 'wrong-one' not in json.dumps(result)


def test_ca_certificate_needs_2_15(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/registries/%d' % rid(server), 'registry_update')
    result = run_module(registry.main, dict(name='rr-fixtures-self', ca_certificate='-----BEGIN CERTIFICATE-----\nx\n'))
    if server.version == '2.14':
        assert result['failed'] is True and '2.15' in result['msg']
    else:
        assert result['changed'] is True
        assert 'ca_certificate' in server.calls('PUT')[0]['body']


def test_delete(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    server.route('DELETE', '/registries/%d' % rid(server), 'registry_delete')
    result = run_module(registry.main, dict(name='rr-fixtures-self', state='absent'))
    assert result['changed'] is True


def test_delete_in_use_reported(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    server.route('DELETE', '/registries/%d' % rid(server), 'registry_delete_in_use')
    result = run_module(registry.main, dict(name='rr-fixtures-self', state='absent'))
    assert result['failed'] is True
    assert result['request_details']['status'] == 412


def test_delete_missing(server, run_module):
    server.route('GET', '/registries', 'registry_list_before')
    result = run_module(registry.main, dict(name='rr-fixtures-self', state='absent'))
    assert result['changed'] is False


def test_registry_info(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    result = run_module(registry_info.main, dict(name='rr-fixtures-auth'))
    reg = result['registries'][0]
    assert reg['access_key'] == 'admin' and reg['has_secret'] is True
    assert '*****' not in json.dumps(result)


def test_rejected_secret_with_quotes_is_not_reported(server, run_module):
    # Ansible only masks a secret that appears exactly as passed; in a JSON
    # string the quote is escaped.
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/registries/%d' % aid(server), 'registry_update_bad_secret')
    result = run_module(registry.main, dict(name='rr-fixtures-auth', access_secret='wr"ng-Zebra7'))
    assert result['failed'] is True
    assert 'Zebra7' not in json.dumps(result)
    assert result['request_details']['request']['access_secret'] == '********'


def test_access_key_alone_gets_a_credential_type(server, run_module):
    # rr-fixtures-self is stored without a credential.
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/registries/%d' % rid(server), 'registry_update')
    result = run_module(registry.main, dict(name='rr-fixtures-self', access_key='bot'))
    assert result['changed'] is True and result['secret_updated'] is False
    assert server.calls('PUT')[0]['body'] == dict(access_key='bot', credential_type='basic')
    assert result['registry']['credential_type'] == 'basic'


def test_secret_alone_gets_a_credential_type(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/registries/%d' % rid(server), 'registry_update')
    result = run_module(registry.main, dict(name='rr-fixtures-self', access_secret='t0p-secret'))
    assert server.calls('PUT')[0]['body'] == dict(access_secret='t0p-secret', credential_type='basic')
    assert result['registry']['credential_type'] == 'basic'


def test_declared_credential_type_is_sent_with_the_key(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/registries/%d' % rid(server), 'registry_update')
    run_module(registry.main, dict(name='rr-fixtures-self', access_key='bot', credential_type='oauth'))
    assert server.calls('PUT')[0]['body'] == dict(access_key='bot', credential_type='oauth')


def test_stored_credential_type_is_left_alone(server, run_module):
    # rr-fixtures-auth is stored with type basic.
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/registries/%d' % aid(server), 'registry_update')
    run_module(registry.main, dict(name='rr-fixtures-auth', access_key='other'))
    assert server.calls('PUT')[0]['body'] == dict(access_key='other')


def test_unchanged_registry_gets_no_credential_type(server, run_module):
    server.route('GET', '/registries', 'registry_list')
    result = run_module(registry.main, dict(name='rr-fixtures-self', access_key=''))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_credential_type_is_checked_before_any_request(server, run_module):
    result = run_module(registry.main, dict(SELF, credential_type='Basic'))
    assert result['failed'] is True
    assert result['msg'] == 'value of credential_type must be one of: basic, oauth, got: Basic'
    assert server.requests == []


@pytest.mark.parametrize('extra, sent', [(dict(), False), (dict(access_key='admin', access_secret='t0p-secret'), True)])
def test_check_mode_create_reports_what_a_real_run_does(server, run_module, extra, sent):
    server.route('GET', '/registries', 'registry_list_before')
    server.route('POST', '/registries', 'registry_create')
    server.route('GET', '/registries/%d' % rid(server), 'registry_get_with_credential' if sent else 'registry_get')
    real = run_module(registry.main, dict(SELF, **extra))
    check = run_module(registry.main, dict(SELF, **extra), check_mode=True)
    assert real['secret_updated'] is sent
    assert check['secret_updated'] is sent
    assert check['changed'] is real['changed'] is True
