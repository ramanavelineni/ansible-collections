# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import project_member, project_member_info

PROJECT = 'fixtures-member'
USER = dict(project=PROJECT, user='fixtures-member-user')
GROUP = dict(project=PROJECT, group='fixtures-member-group', group_type='oidc')


@pytest.fixture
def base(server):
    """The project's member path; the project is found by name."""
    server.route('GET', '/projects', 'member_projects')
    return '/projects/%d/members' % server.fixtures['member_projects']['body'][0]['project_id']


def mid(server, fixture):
    """The membership id a recorded single-member answer carries."""
    return server.fixtures[fixture]['body']['id']


def auth_mode_answer(server, mode):
    """The recorded configuration answer, hand-edited to another auth_mode (only db_auth was recorded)."""
    answer = server.response('member_configurations')
    answer['body']['auth_mode']['value'] = mode
    return answer


# -- users ---------------------------------------------------------------------

def test_add_user_sends_role_id_and_username(server, base, run_module):
    server.route('GET', base, 'member_list_creator')
    server.route('POST', base, 'member_create_user')
    server.route('GET', '%s/%d' % (base, mid(server, 'member_get_user')), 'member_get_user')
    result = run_module(project_member.main, dict(USER, role='developer'))
    assert result['changed'] is True
    assert server.calls('POST', base)[0]['body'] == dict(role_id=2, member_user=dict(username='fixtures-member-user'))
    assert result['member'] == dict(id=mid(server, 'member_get_user'), project=PROJECT,
                                    project_id=server.fixtures['member_get_user']['body']['project_id'],
                                    user='fixtures-member-user', group=None, group_type=None,
                                    role='developer', role_id=2)
    assert result['diff']['before'] == {}


def test_add_user_in_check_mode_sends_nothing(server, base, run_module):
    server.route('GET', base, 'member_list_creator')
    result = run_module(project_member.main, dict(USER, role='developer'), check_mode=True)
    assert result['changed'] is True
    assert result['member']['id'] is None and result['member']['role'] == 'developer'
    assert server.calls('POST') == []


def test_member_with_the_same_role_is_left_alone(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    result = run_module(project_member.main, dict(USER, role='developer'))
    assert result['changed'] is False
    assert result['member']['role'] == 'developer'
    assert server.calls('PUT') == [] and server.calls('POST') == []


def test_role_left_out_changes_nothing_for_an_existing_member(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    result = run_module(project_member.main, dict(USER))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_role_change_sends_only_the_role_and_returns_what_harbor_stored(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    path = '%s/%d' % (base, mid(server, 'member_get_user'))
    server.route('PUT', path, 'member_update')
    server.route('GET', path, 'member_get_updated')
    result = run_module(project_member.main, dict(USER, role='maintainer'))
    assert result['changed'] is True
    assert server.calls('PUT', path)[0]['body'] == dict(role_id=4)
    assert result['diff']['before']['role'] == 'developer'
    assert result['member']['role'] == 'maintainer' and result['member']['role_id'] == 4
    assert result['diff']['after'] == result['member']
    assert not result.get('warnings')


def test_role_change_harbor_did_not_store_is_warned_about(server, base, run_module):
    # The read after the write answers the old role (the recorded member before the update).
    server.route('GET', base, 'member_list_all')
    path = '%s/%d' % (base, mid(server, 'member_get_user'))
    server.route('PUT', path, 'member_update')
    server.route('GET', path, 'member_get_user')
    result = run_module(project_member.main, dict(USER, role='maintainer'))
    assert result['member']['role'] == 'developer'
    assert 'role' in str(result['warnings'])


def test_role_change_in_check_mode_predicts_the_real_result(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    path = '%s/%d' % (base, mid(server, 'member_get_user'))
    server.route('PUT', path, 'member_update')
    server.route('GET', path, 'member_get_updated')
    real = run_module(project_member.main, dict(USER, role='maintainer'))
    check = run_module(project_member.main, dict(USER, role='maintainer'), check_mode=True)
    assert check['member'] == real['member'] and check['diff'] == real['diff']


def test_adding_a_member_needs_a_role(server, base, run_module):
    server.route('GET', base, 'member_list_creator')
    result = run_module(project_member.main, dict(USER))
    assert result['failed'] is True
    assert result['msg'] == "Adding user 'fixtures-member-user' to project 'fixtures-member' needs role."
    assert server.calls('POST') == []


def test_unknown_user_reports_harbors_answer(server, base, run_module):
    server.route('GET', base, 'member_list_creator')
    server.route('POST', base, 'member_create_unknown_user')
    result = run_module(project_member.main, dict(project=PROJECT, user='fixtures-member-nobody', role='developer'))
    assert result['failed'] is True
    assert 'user fixtures-member-nobody is not found' in result['msg']


def test_user_is_not_mistaken_for_a_group_of_the_same_name(server, base, run_module):
    # Hand-made: the recorded group member, renamed after the user.
    listing = server.response('member_list_all')
    group = [m for m in listing['body'] if m['entity_type'] == 'g'][0]
    group['entity_name'] = 'fixtures-member-user'
    listing['body'] = [m for m in listing['body'] if m['entity_type'] == 'g' or m['entity_name'] == 'admin']
    listing['headers']['x-total-count'] = str(len(listing['body']))
    server.route('GET', base, listing)
    server.route('POST', base, 'member_create_user')
    server.route('GET', '%s/%d' % (base, mid(server, 'member_get_user')), 'member_get_user')
    result = run_module(project_member.main, dict(USER, role='developer'))
    assert result['changed'] is True
    assert len(server.calls('POST', base)) == 1


# -- groups --------------------------------------------------------------------

def test_existing_group_is_added_by_its_id(server, base, run_module):
    server.route('GET', base, 'member_list_creator')
    server.route('GET', '/usergroups', 'member_usergroups_one')
    server.route('POST', base, 'member_create_group')
    server.route('GET', '%s/%d' % (base, mid(server, 'member_get_group')), 'member_get_group')
    result = run_module(project_member.main, dict(GROUP, role='guest'))
    assert result['changed'] is True
    gid = server.fixtures['member_usergroups_one']['body'][0]['id']
    assert server.calls('POST', base)[0]['body'] == dict(role_id=3, member_group=dict(id=gid))
    assert result['member']['group'] == 'fixtures-member-group'
    assert result['member']['group_type'] == 'oidc' and result['member']['role'] == 'guest'
    assert result['member']['user'] is None
    # The group exists, so the auth mode doesn't matter and isn't read.
    assert server.calls('GET', '/configurations') == []


def test_group_member_is_found_by_the_groups_id(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    server.route('GET', '/usergroups', 'member_usergroups_one')
    result = run_module(project_member.main, dict(GROUP, role='guest'))
    assert result['changed'] is False
    assert result['member']['id'] == mid(server, 'member_get_group')


def test_group_of_another_type_is_not_taken_for_the_member_with_that_name(server, base, run_module):
    # The project has the OIDC group as a member; an LDAP group of the same name is another group.
    server.route('GET', base, 'member_list_all')
    server.route('GET', '/usergroups', 'member_usergroups_one')
    server.route('GET', '/configurations', 'member_configurations')
    result = run_module(project_member.main, dict(GROUP, group_type='ldap', role='guest'))
    assert result['failed'] is True
    assert "Harbor has no ldap group 'fixtures-member-group'" in result['msg']
    assert server.calls('POST') == []


def test_missing_group_fails_with_the_reason_when_harbor_cannot_create_it(server, base, run_module):
    server.route('GET', base, 'member_list_creator')
    server.route('GET', '/usergroups', 'member_usergroups_empty')
    server.route('GET', '/configurations', 'member_configurations')
    result = run_module(project_member.main, dict(GROUP, role='guest'))
    assert result['failed'] is True
    assert result['msg'].startswith(
        "Harbor has no oidc group 'fixtures-member-group', and creates a missing one only while its auth_mode is "
        'oidc_auth; it is db_auth.')
    assert server.calls('POST') == []


def test_missing_group_is_a_warning_in_check_mode(server, base, run_module):
    server.route('GET', base, 'member_list_creator')
    server.route('GET', '/usergroups', 'member_usergroups_empty')
    server.route('GET', '/configurations', 'member_configurations')
    result = run_module(project_member.main, dict(GROUP, role='guest'), check_mode=True)
    assert result['changed'] is True
    assert 'auth_mode is oidc_auth; it is db_auth' in str(result['warnings'])
    assert server.calls('POST') == []


def test_missing_group_is_sent_by_name_and_type_when_harbor_can_create_it(server, base, run_module):
    server.route('GET', base, 'member_list_creator')
    server.route('GET', '/usergroups', 'member_usergroups_empty')
    server.route('GET', '/configurations', auth_mode_answer(server, 'oidc_auth'))
    server.route('POST', base, 'member_create_group')
    server.route('GET', '%s/%d' % (base, mid(server, 'member_get_group')), 'member_get_group')
    result = run_module(project_member.main, dict(GROUP, role='guest'))
    assert result['changed'] is True
    assert server.calls('POST', base)[0]['body'] == dict(
        role_id=3, member_group=dict(group_name='fixtures-member-group', group_type=3))


def test_auth_mode_that_lists_only_its_own_group_type_leaves_the_decision_to_harbor(server, base, run_module):
    # Under ldap_auth Harbor lists only LDAP groups, so an OIDC group may exist unlisted.
    server.route('GET', base, 'member_list_creator')
    server.route('GET', '/usergroups', 'member_usergroups_empty')
    server.route('GET', '/configurations', auth_mode_answer(server, 'ldap_auth'))
    server.route('POST', base, 'member_create_unknown_group')
    result = run_module(project_member.main, dict(GROUP, role='guest'))
    assert result['failed'] is True
    assert 'not found: not supported' in result['msg']
    sent = server.calls('POST', base)[0]['body']['member_group']
    assert sent == dict(group_name='fixtures-member-group', group_type=3)


def test_without_access_to_user_groups_a_group_is_found_by_name(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    server.route('GET', '/usergroups', 'member_usergroups_anonymous')
    result = run_module(project_member.main, dict(GROUP, role='guest'))
    assert result['changed'] is False
    assert result['member']['id'] == mid(server, 'member_get_group')
    assert server.calls('GET', '/configurations') == []


def test_without_access_to_user_groups_two_groups_with_that_name_fail(server, base, run_module):
    # Hand-made: the recorded group member twice, as an OIDC and an LDAP group of one name would be listed.
    listing = server.response('member_list_all')
    group = [m for m in listing['body'] if m['entity_type'] == 'g'][0]
    listing['body'].append(dict(group, id=group['id'] + 100, entity_id=group['entity_id'] + 100))
    server.route('GET', base, listing)
    server.route('GET', '/usergroups', 'member_usergroups_anonymous')
    result = run_module(project_member.main, dict(GROUP, role='guest'))
    assert result['failed'] is True
    assert "has 2 group members named 'fixtures-member-group'" in result['msg']


# -- removal -------------------------------------------------------------------

def test_remove_member(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    path = '%s/%d' % (base, mid(server, 'member_get_user'))
    server.route('DELETE', path, 'member_delete')
    result = run_module(project_member.main, dict(USER, state='absent'))
    assert result['changed'] is True
    assert result['member'] == {}
    assert result['diff']['before']['user'] == 'fixtures-member-user'
    assert len(server.calls('DELETE', path)) == 1


def test_removal_harbor_answers_200_for_a_membership_that_is_already_gone(server, base, run_module):
    # The membership was listed and removed by someone else before the delete arrived: Harbor
    # answers that delete with 200 as well (recorded), so the task reports the removal.
    server.route('GET', base, 'member_list_all')
    server.route('DELETE', '%s/%d' % (base, mid(server, 'member_get_user')), 'member_delete_missing')
    result = run_module(project_member.main, dict(USER, state='absent'))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is True


@pytest.mark.parametrize('name', ['team/app', 'a&b=c', 'x#1+y%20', 'r\u00e9gis \u00fc'])
def test_user_name_goes_into_the_body_and_the_member_is_removed_by_id(server, base, run_module, name):
    # Hand-edited: the recorded user member under another name.
    listing = server.response('member_list_all')
    for member in listing['body']:
        if member['entity_name'] == 'fixtures-member-user':
            member['entity_name'] = name
    server.route('GET', base, listing)
    path = '%s/%d' % (base, mid(server, 'member_get_user'))
    server.route('DELETE', path, 'member_delete')
    result = run_module(project_member.main, dict(project=PROJECT, user=name, state='absent'))
    assert result['changed'] is True
    assert [r['path'] for r in server.requests if r['method'] == 'DELETE'] == [path]


def test_remove_member_that_is_gone_reports_no_change(server, base, run_module):
    server.route('GET', base, 'member_list_after_delete')
    result = run_module(project_member.main, dict(USER, state='absent'))
    assert result['changed'] is False
    assert server.calls('DELETE') == []


def test_remove_from_a_project_that_is_gone_reports_no_change(server, run_module):
    server.route('GET', '/projects', dict(status=200, body=[], headers={'x-total-count': '0'}))
    result = run_module(project_member.main, dict(USER, state='absent'))
    assert result['changed'] is False


def test_unknown_project_fails(server, run_module):
    server.route('GET', '/projects', dict(status=200, body=[], headers={'x-total-count': '0'}))
    result = run_module(project_member.main, dict(USER, role='developer'))
    assert result['failed'] is True
    assert "Project 'fixtures-member' does not exist" in result['msg']


# -- options -------------------------------------------------------------------

@pytest.mark.parametrize('args, message', [
    (dict(project=PROJECT, role='guest'), 'one of the following is required: user, group'),
    (dict(USER, group='g', group_type='oidc'), 'parameters are mutually exclusive: user|group'),
    (dict(USER, group_type='oidc'), 'parameters are mutually exclusive: user|group_type'),
    (dict(project=PROJECT, group='g', role='guest'), 'missing parameter(s) required by \'group\': group_type'),
])
def test_options_that_do_not_name_one_member_are_refused(server, run_module, args, message):
    result = run_module(project_member.main, args)
    assert result['failed'] is True
    assert message in result['msg']
    assert server.requests == []


# -- project_member_info -------------------------------------------------------

def test_info_lists_users_then_groups_with_the_group_type(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    server.route('GET', '/usergroups', 'member_usergroups_all')
    members = run_module(project_member_info.main, dict(project=PROJECT))['members']
    assert [(m['user'], m['group'], m['group_type'], m['role']) for m in members] == [
        ('admin', None, None, 'project_admin'),
        ('fixtures-member-user', None, None, 'developer'),
        (None, 'fixtures-member-group', 'oidc', 'guest'),
    ]


def test_info_group_type_is_null_for_a_user_who_may_not_read_user_groups(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    server.route('GET', '/usergroups', 'member_usergroups_anonymous')
    result = run_module(project_member_info.main, dict(project=PROJECT))
    assert result.get('failed') is not True, result.get('msg')
    group = [m for m in result['members'] if m['group']][0]
    assert group['group_type'] is None and group['role'] == 'guest'


def test_info_by_name(server, base, run_module):
    server.route('GET', base, 'member_list_all')
    server.route('GET', '/usergroups', 'member_usergroups_all')
    members = run_module(project_member_info.main, dict(project=PROJECT, name='fixtures-member-group'))['members']
    assert [m['group'] for m in members] == ['fixtures-member-group']


def test_info_reads_no_user_groups_when_there_is_no_group_member(server, base, run_module):
    server.route('GET', base, 'member_list_creator')
    members = run_module(project_member_info.main, dict(project=PROJECT))['members']
    assert [m['user'] for m in members] == ['admin']
    assert server.calls('GET', '/usergroups') == []
