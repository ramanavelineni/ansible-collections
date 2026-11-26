# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""role and role_info, from the answers recorded in the role area (Harbor 2.16; 2.15 has no /roles)."""

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import role, role_info

NAME = 'fixtures-role-ci'
ACCESS = [dict(resource='repository', action='pull'), dict(resource='repository', action='push')]
WANTED = dict(name=NAME, description='recorded', permissions=ACCESS)


def has_roles(server):
    return server.version >= '2.16'


def rid(server):
    return server.fixtures['role_create']['body']['id']


def listing(server, fixture):
    """A recorded role listing; on 2.15 the routes are never reached (the module stops first)."""
    server.route('GET', '/roles', fixture)
    server.route('GET', '/permissions', 'role_permissions')


# -- before 2.16 ---------------------------------------------------------------

def test_older_harbor_has_no_custom_roles(server, run_module):
    if has_roles(server):
        pytest.skip('Harbor %s has custom roles' % server.version)
    # Recorded: 2.15 answers 404 for /roles; the module says why before asking.
    assert server.fixtures['role_list_before']['status'] == 404
    for main, args in ((role.main, WANTED), (role_info.main, {})):
        result = run_module(main, args)
        assert result['failed'] is True
        assert 'need Harbor 2.16' in result['msg']
    assert [r['path'] for r in server.requests if r['path'] != '/systeminfo'] == []


@pytest.fixture
def roles_server(server):
    if not has_roles(server):
        pytest.skip('Harbor %s has no custom roles (see test_older_harbor_has_no_custom_roles)' % server.version)
    return server


# -- create, update, delete ----------------------------------------------------

def test_create(roles_server, run_module):
    server = roles_server
    listing(server, 'role_list_before')
    server.route('POST', '/roles', 'role_create')
    server.route('GET', '/roles/%d' % rid(server), 'role_get')
    result = run_module(role.main, WANTED)
    assert result['changed'] is True
    assert result['role']['id'] == rid(server)
    assert result['role']['permissions'] == ACCESS
    assert result['role']['builtin'] is False and result['role']['member_role'] == NAME
    assert server.calls('POST', '/roles')[0]['body'] == dict(
        name=NAME, description='recorded', permissions=[dict(kind='project-role', namespace='*', access=ACCESS)])


def test_create_check_mode_predicts_the_real_result(roles_server, run_module):
    server = roles_server
    listing(server, 'role_list_before')
    server.route('POST', '/roles', 'role_create')
    server.route('GET', '/roles/%d' % rid(server), 'role_get')
    check = run_module(role.main, WANTED, check_mode=True)
    real = run_module(role.main, WANTED)
    assert check['changed'] is True and server.calls('POST')[1:] == []
    assert dict(check['role'], id=None) == dict(real['role'], id=None)


def test_create_needs_permissions(roles_server, run_module):
    listing(roles_server, 'role_list_before')
    result = run_module(role.main, dict(name=NAME))
    assert result['failed'] is True and 'needs permissions' in result['msg']
    assert roles_server.calls('POST') == []


def test_no_change(roles_server, run_module):
    listing(roles_server, 'role_list_one')
    result = run_module(role.main, dict(WANTED, permissions=list(reversed(ACCESS)) + ACCESS[:1]))
    assert result['changed'] is False
    assert roles_server.calls('PUT') == []


def test_update_sends_description_and_permissions(roles_server, run_module):
    server = roles_server
    listing(server, 'role_list_one')
    server.route('PUT', '/roles/%d' % rid(server), 'role_update')
    server.route('GET', '/roles/%d' % rid(server), 'role_get_updated')
    result = run_module(role.main, dict(name=NAME, description='changed', permissions=ACCESS[:1]))
    assert result['changed'] is True
    assert result['diff']['before']['permissions'] == ACCESS
    assert result['role']['permissions'] == ACCESS[:1] and result['role']['description'] == 'changed'
    assert not result.get('warnings')
    assert server.calls('PUT')[0]['body'] == dict(
        name=NAME, description='changed', permissions=[dict(kind='project-role', namespace='*', access=ACCESS[:1])])


def test_description_alone_sends_the_stored_permissions_back(roles_server, run_module):
    # Harbor refuses an update without permissions (recorded at create: "empty permission").
    server = roles_server
    listing(server, 'role_list_one')
    server.route('PUT', '/roles/%d' % rid(server), 'role_update')
    server.route('GET', '/roles/%d' % rid(server), 'role_get')
    run_module(role.main, dict(name=NAME, description='only this'))
    assert server.calls('PUT')[0]['body']['permissions'][0]['access'] == ACCESS


def test_delete(roles_server, run_module):
    server = roles_server
    listing(server, 'role_list_one')
    server.route('DELETE', '/roles/%d' % rid(server), 'role_delete')
    result = run_module(role.main, dict(name=NAME, state='absent'))
    assert result['changed'] is True and result['role'] == {}


def test_delete_missing_is_no_change(roles_server, run_module):
    listing(roles_server, 'role_list_before')
    result = run_module(role.main, dict(name=NAME, state='absent'))
    assert result['changed'] is False
    assert roles_server.calls('DELETE') == []


def test_delete_in_use_passes_harbors_refusal_on(roles_server, run_module):
    server = roles_server
    listing(server, 'role_list_one')
    server.route('DELETE', '/roles/%d' % rid(server), 'role_delete_in_use')
    result = run_module(role.main, dict(name=NAME, state='absent'))
    assert result['failed'] is True
    assert 'still assigned to 1 project member' in result['msg']


# -- what is refused first -------------------------------------------------------

@pytest.mark.parametrize('name', ['developer', 'projectAdmin', 'project_admin', 'limited_guest'])
def test_built_in_role_names_are_refused(server, run_module, name):
    result = run_module(role.main, dict(WANTED, name=name))
    assert result['failed'] is True and 'built-in role' in result['msg']
    assert [r['path'] for r in server.requests if r['path'] != '/systeminfo'] == []
    if has_roles(server):
        # What Harbor answers, too (recorded).
        assert server.fixtures['role_update_builtin']['status'] == 403


def test_empty_permissions_are_refused(roles_server, run_module):
    listing(roles_server, 'role_list_before')
    result = run_module(role.main, dict(name=NAME, permissions=[]))
    assert result['failed'] is True and 'permissions cannot be empty' in result['msg']
    assert roles_server.fixtures['role_create_empty']['status'] == 400


def test_a_permission_harbor_does_not_offer_is_refused(roles_server, run_module):
    listing(roles_server, 'role_list_before')
    result = run_module(role.main, dict(name=NAME, permissions=[dict(resource='nope', action='pull')]))
    assert result['failed'] is True and 'offers no role permission nope:pull' in result['msg']
    assert roles_server.calls('POST') == []
    assert roles_server.fixtures['role_create_bad_permission']['status'] == 400


@pytest.mark.parametrize('status', [401, 403])
def test_unreadable_permissions_are_left_to_harbor(roles_server, run_module, status):
    server = roles_server
    server.route('GET', '/roles', 'role_list_before')
    server.route('GET', '/permissions', dict(status=status, body={'errors': [{'code': 'FORBIDDEN'}]}, headers={}))
    server.route('POST', '/roles', 'role_create_bad_permission')
    result = run_module(role.main, dict(name=NAME, permissions=[dict(resource='nope', action='pull')]))
    assert result['failed'] is True and 'nope:pull' in result['msg']
    assert len(server.calls('POST')) == 1


# -- role_info -----------------------------------------------------------------

def test_role_info_lists_built_in_roles_first(roles_server, run_module):
    listing(roles_server, 'role_list_one')
    roles = run_module(role_info.main, {})['roles']
    assert [(r['name'], r['builtin'], r['member_role']) for r in roles] == [
        ('developer', True, 'developer'), ('guest', True, 'guest'), ('limitedGuest', True, 'limited_guest'),
        ('maintainer', True, 'maintainer'), ('projectAdmin', True, 'project_admin'), (NAME, False, NAME)]
    # A built-in role's permission on the project itself has no resource.
    assert dict(resource='', action='read') in roles[0]['permissions']


def test_role_info_custom_only_and_by_name(roles_server, run_module):
    listing(roles_server, 'role_list_one')
    assert [r['name'] for r in run_module(role_info.main, dict(custom_only=True))['roles']] == [NAME]
    assert [r['id'] for r in run_module(role_info.main, dict(name='guest'))['roles']] == [3]
