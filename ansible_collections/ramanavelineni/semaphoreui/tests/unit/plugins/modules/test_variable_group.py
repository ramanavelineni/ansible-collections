# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import variable_group, variable_group_info

VG = dict(project='homelab', name='harbor', json=dict(harbor_url='https://harbor.example.com'), env=dict(TZ='UTC'),
          secrets=[dict(name='TOKEN', type='env', value='tok-1'), dict(name='db_pw', type='var', value='pw-1')])


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    return base


def group_id(server):
    return server.fixtures['variable_group_create']['body']['id']


def existing(server, project, fixture='variable_group_get'):
    server.route('GET', project + '/environment', 'variable_groups_one')
    server.route('GET', '%s/environment/%d' % (project, group_id(server)), fixture)
    server.route('PUT', '%s/environment/%d' % (project, group_id(server)), 'variable_group_update')


def secret_id(server, name, fixture='variable_group_get'):
    return [s for s in server.fixtures[fixture]['body']['secrets'] if s['name'] == name][0]['id']


def test_create(server, project, run_module):
    server.route('GET', project + '/environment', 'variable_groups_empty')
    server.route('POST', project + '/environment', 'variable_group_create')
    result = run_module(variable_group.main, VG)
    assert result['changed'] is True
    assert result['variable_group']['id'] == group_id(server)
    assert sorted(result['secrets_sent']) == ['TOKEN', 'db_pw']
    body = server.calls('POST', project + '/environment')[0]['body']
    assert json.loads(body['json']) == VG['json']
    assert json.loads(body['env']) == VG['env']
    assert body['secrets'] == [
        dict(name='TOKEN', type='env', secret='tok-1', operation='create'),
        dict(name='db_pw', type='var', secret='pw-1', operation='create')]
    assert 'tok-1' not in json.dumps(result)


def test_create_secret_needs_value(server, project, run_module):
    server.route('GET', project + '/environment', 'variable_groups_empty')
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', secrets=[dict(name='TOKEN')]))
    assert result['failed'] is True
    assert 'needs its value' in result['msg']


def test_env_values_must_be_scalar(server, project, run_module):
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', env=dict(X=[1])))
    assert result['failed'] is True
    assert 'scalar' in result['msg']


def test_duplicate_secret_names(server, project, run_module):
    result = run_module(variable_group.main, dict(project='homelab', name='harbor',
                                                  secrets=[dict(name='A', value='1'), dict(name='A', value='2')]))
    assert result['failed'] is True
    assert 'more than once' in result['msg']


def test_always_resends_values(server, project, run_module):
    existing(server, project)
    result = run_module(variable_group.main, VG)
    assert result['changed'] is True
    ops = server.calls('PUT')[0]['body']['secrets']
    assert sorted((o['name'], o['operation'], o['secret']) for o in ops) == [
        ('TOKEN', 'update', 'tok-1'), ('db_pw', 'update', 'pw-1')]
    assert all(o['id'] for o in ops)


def test_on_create_is_idempotent(server, project, run_module):
    existing(server, project)
    result = run_module(variable_group.main, dict(VG, update_secret='on_create'))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_json_compared_as_data(server, project, run_module):
    existing(server, project)
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', json=VG['json'], env=VG['env']))
    assert result['changed'] is False


def test_env_change_keeps_json_and_passthrough(server, project, run_module):
    existing(server, project)
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', env=dict(TZ='Europe/Oslo')))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    current = server.fixtures['variable_group_get']['body']
    assert json.loads(body['env']) == dict(TZ='Europe/Oslo')
    assert body['json'] == current['json']
    assert body['secrets'] == []
    assert body['id'] == group_id(server)
    for field in ('password', 'sync_enabled', 'sync_interval', 'sync_paths'):
        assert body[field] == current[field]


def test_type_change_recreates(server, project, run_module):
    existing(server, project)
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', update_secret='on_create',
                                                  secrets=[dict(name='TOKEN', type='var', value='tok-2')]))
    assert result['changed'] is True
    assert result['secrets_deleted'] == ['TOKEN']
    assert result['secrets_sent'] == ['TOKEN']
    assert server.calls('PUT')[0]['body']['secrets'] == [
        dict(id=secret_id(server, 'TOKEN'), name='TOKEN', type='env', secret='', operation='delete'),
        dict(name='TOKEN', type='var', secret='tok-2', operation='create')]


def test_type_change_needs_value(server, project, run_module):
    existing(server, project)
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', secrets=[dict(name='TOKEN', type='var')]))
    assert result['failed'] is True
    assert 'cannot change that in place' in result['msg']


def test_purge(server, project, run_module):
    existing(server, project)
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', purge_secrets=True,
                                                  secrets=[dict(name='TOKEN', type='env')]))
    assert result['changed'] is True
    assert result['secrets_deleted'] == ['db_pw']
    assert [s['name'] for s in result['variable_group']['secrets']] == ['TOKEN']


def test_undeclared_secrets_left_alone(server, project, run_module):
    existing(server, project)
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', secrets=[dict(name='TOKEN', type='env')]))
    assert result['changed'] is False


def test_rejected_update(server, project, run_module):
    existing(server, project)
    server.route('PUT', '%s/environment/%d' % (project, group_id(server)), 'variable_group_update_id_mismatch')
    result = run_module(variable_group.main, VG)
    assert result['failed'] is True
    assert 'Environment ID in body and URL must be the same' in result['msg']
    assert 'tok-1' not in json.dumps(result)


def test_delete(server, project, run_module):
    existing(server, project)
    server.route('GET', '%s/environment/%d/refs' % (project, group_id(server)), 'variable_group_refs_unused')
    server.route('DELETE', '%s/environment/%d' % (project, group_id(server)), 'variable_group_delete')
    stored = run_module(variable_group.main, dict(project='homelab', name='harbor'))['variable_group']
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', state='absent'))
    assert result['changed'] is True
    assert len(server.calls('DELETE')) == 1
    # The diff shows what is deleted, in the shape an update shows it: secrets by name and type only.
    assert result['diff'] == dict(before=stored, after={})
    assert stored['json'] and sorted(s['name'] for s in stored['secrets']) == ['TOKEN', 'db_pw']
    assert all(sorted(s) == ['name', 'type'] for s in stored['secrets'])


# -- stored json or env that is not valid JSON ----------------------------------
# Hand-made: the recorded group with one field broken, as a write that bypassed
# the UI would leave it.

def broken(server, project, field):
    group = server.response('variable_group_get')
    group['body'][field] = '{not json'
    existing(server, project, fixture=group)
    return group['body']


def test_invalid_stored_json_is_replaced(server, project, run_module):
    stored = broken(server, project, 'json')
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', json=dict(a=1)))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    assert json.loads(body['json']) == dict(a=1)
    assert body['env'] == stored['env']
    # The diff shows the text Semaphore held, since it can't be shown parsed.
    assert result['diff']['before']['json'] == '{not json'
    assert result['diff']['after']['json'] == dict(a=1)
    assert result['variable_group']['json'] == dict(a=1)


def test_invalid_stored_env_is_replaced_in_check_mode(server, project, run_module):
    broken(server, project, 'env')
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', env=dict(TZ='UTC')), check_mode=True)
    assert result['changed'] is True
    assert result['diff']['before']['env'] == '{not json'
    assert server.calls('PUT') == []


@pytest.mark.parametrize('args', [dict(), dict(env=dict(TZ='UTC')), dict(secrets=[dict(name='TOKEN', type='env')])],
                         ids=['nothing', 'other-field', 'secrets'])
def test_invalid_stored_json_left_alone_still_fails(server, project, run_module, args):
    # An update sends the field back as it is, so the module won't write around it.
    broken(server, project, 'json')
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', **args))
    assert result['failed'] is True
    assert 'not valid JSON; fix them in Semaphore first' in result['msg']
    assert server.calls('PUT') == []


def test_invalid_stored_json_does_not_block_delete(server, project, run_module):
    broken(server, project, 'json')
    server.route('GET', '%s/environment/%d/refs' % (project, group_id(server)), 'variable_group_refs_unused')
    server.route('DELETE', '%s/environment/%d' % (project, group_id(server)), 'variable_group_delete')
    result = run_module(variable_group.main, dict(project='homelab', name='harbor', state='absent'))
    assert result['changed'] is True
    assert result['diff']['before']['json'] == '{not json'
    assert len(server.calls('DELETE')) == 1


def test_variable_group_info(server, project, run_module):
    server.route('GET', project + '/environment', 'variable_groups_one')
    server.route('GET', '%s/environment/%d' % (project, group_id(server)), 'variable_group_get_updated')
    result = run_module(variable_group_info.main, dict(project='homelab'))
    group = result['variable_groups'][0]
    assert group['env'] == dict(TZ='Europe/Oslo')
    assert group['json'] == dict(harbor_url='https://harbor.example.com')
    assert group['secrets'] == [dict(name='TOKEN', type='var'), dict(name='db_pw', type='var')]
