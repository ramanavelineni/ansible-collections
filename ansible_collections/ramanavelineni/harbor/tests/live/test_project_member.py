# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""project_member and project_member_info against a real Harbor.

The throwaway servers use database logins. An OIDC group is created through
/usergroups, which Harbor allows in any auth mode, so a group member can be
added there; a group that doesn't exist can't be, and the module says why.
"""

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import project_member, project_member_info
from ansible_collections.ramanavelineni.harbor.tests.live.conftest import PREFIX, changed, header

USER = PREFIX + 'member-dev'
GROUP = PREFIX + 'group'


@pytest.fixture
def user(api):
    for leftover in api.listing('/users?q=username%%3D%s' % USER):
        api.ok('DELETE', '/users/%d' % leftover['user_id'])
    api.create_user(USER)
    yield USER
    for leftover in api.listing('/users?q=username%%3D%s' % USER):
        api.ok('DELETE', '/users/%d' % leftover['user_id'])


@pytest.fixture
def group(api):
    """An OIDC user group of the suite's own."""
    for leftover in api.listing('/usergroups?group_name=%s' % GROUP):
        if leftover['group_name'] == GROUP:
            api.ok('DELETE', '/usergroups/%d' % leftover['id'])
    dummy, headers = api.ok('POST', '/usergroups', dict(group_name=GROUP, group_type=3))
    yield int(header(headers, 'Location').rsplit('/', 1)[1])
    for leftover in api.listing('/usergroups?group_name=%s' % GROUP):
        if leftover['group_name'] == GROUP:
            api.ok('DELETE', '/usergroups/%d' % leftover['id'])


def members(api, project):
    return api.listing('/projects/%d/members' % api.projects(project)[0]['project_id'])


def test_user_member_is_added_changed_and_removed(api, run, project, user):
    task = dict(project=project, user=user, role='developer')
    would = run(project_member.main, task, check=True)
    assert changed(would) is True
    assert [m for m in members(api, project) if m['entity_name'] == user] == []

    added = run(project_member.main, task)
    assert changed(added) is True
    assert added['member']['role'] == 'developer' and added['member']['id'] is not None
    assert changed(run(project_member.main, task)) is False

    promoted = run(project_member.main, dict(task, role='maintainer'))
    assert changed(promoted) is True
    assert [m['role_id'] for m in members(api, project) if m['entity_name'] == user] == [4]
    listed = run(project_member_info.main, dict(project=project, name=user))
    assert listed['members'] == [promoted['member']]

    gone = dict(project=project, user=user, state='absent')
    assert changed(run(project_member.main, gone)) is True
    assert changed(run(project_member.main, gone)) is False
    assert [m for m in members(api, project) if m['entity_name'] == user] == []


def test_group_member_is_added_by_its_id(api, run, project, group):
    task = dict(project=project, group=GROUP, group_type='oidc', role='guest')
    added = run(project_member.main, task)
    assert changed(added) is True
    assert added['member']['group_type'] == 'oidc' and added['member']['role'] == 'guest'
    stored = [m for m in members(api, project) if m['entity_type'] == 'g']
    assert [(m['entity_id'], m['role_id']) for m in stored] == [(group, 3)]
    assert changed(run(project_member.main, task)) is False
    listed = run(project_member_info.main, dict(project=project))
    assert [m for m in listed['members'] if m['group']] == [added['member']]
    # An LDAP group of the same name is another group, not this member.
    other = run(project_member.main, dict(task, group_type='ldap'))
    assert other.get('failed') is True
    assert changed(run(project_member.main, dict(task, state='absent'))) is True


def test_missing_group_is_refused_with_the_reason(api, run, project):
    mode, dummy = api.ok('GET', '/configurations')
    if mode['auth_mode']['value'] != 'db_auth':
        pytest.skip('this Harbor does not use database logins')
    task = dict(project=project, group=PREFIX + 'nogroup', group_type='oidc', role='guest')
    would = run(project_member.main, task, check=True)
    assert changed(would) is True
    assert 'auth_mode is oidc_auth; it is db_auth' in str(would['warnings'])
    refused = run(project_member.main, task)
    assert refused.get('failed') is True
    assert 'auth_mode is oidc_auth; it is db_auth' in refused['msg']
    assert [m for m in members(api, project) if m['entity_type'] == 'g'] == []


def test_a_project_admin_adds_a_group_without_reading_user_groups(api, run, project, member, group):
    # A project admin who is no system administrator may not list user
    # groups; the module then names the group by name and type, and Harbor finds it.
    task = dict(member, project=project, group=GROUP, group_type='oidc', role='guest')
    added = run(project_member.main, task)
    assert changed(added) is True
    assert [m['entity_id'] for m in members(api, project) if m['entity_type'] == 'g'] == [group]
    assert changed(run(project_member.main, task)) is False
    listed = run(project_member_info.main, dict(member, project=project, name=GROUP))
    assert listed['members'][0]['group_type'] is None
