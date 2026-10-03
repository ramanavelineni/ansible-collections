# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""A login lock that starts after the login check: /projects answers 200 with the public projects only.

Nothing in such an answer says it is anonymous, so the modules check the login
again before they act on a project that is not in it (read_as_user). No
anonymous /projects answer was ever recorded. The ones here are what an
anonymous request gets as the client's notes describe it: the recorded list
without the private project, or (hand-written, marked below) an empty list.
"""

import itertools
import time

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import LOGIN_LOCK_WAIT
from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    project,
    project_info,
    robot_account,
    robot_account_info,
    tag_immutability_info,
    tag_retention_info,
    webhook,
    webhook_info,
)

NAME = 'fixtures-core'
# Hand-written: the answer to GET /projects?name=<a private project> when it
# is handled as anonymous.
NO_PROJECTS = dict(status=200, body=[], headers={'x-total-count': '0'})


def lock_waits():
    return [c for c in time.sleep.call_args_list if c.args == (LOGIN_LOCK_WAIT,)]


def login(server, *later):
    """/systeminfo answers: the login check at the start passes, `later` are the answers after it."""
    server.route('GET', '/systeminfo', 'systeminfo', *later)


def locked_once(server):
    """A lock is on when the login is checked again, and over after the wait."""
    login(server, 'systeminfo_anonymous', 'systeminfo')


def locked_for_good(server):
    login(server, 'systeminfo_anonymous')


def pid(server):
    return int(server.fixtures['project_create']['headers']['location'].rsplit('/', 1)[-1])


def private_project(server, *listings):
    """`listings` are the answers to GET /projects, in order; the project itself is fixtures-core."""
    server.route('GET', '/projects', *listings)
    server.route('GET', '/registries', 'registries_empty')
    server.route('GET', '/quotas', 'quotas_created')
    server.route('DELETE', '/projects/%d' % pid(server), 'project_delete')
    server.route('POST', '/projects', 'project_create')
    server.route('GET', '/projects/%d' % pid(server), 'project_get')


# -- project: state absent -----------------------------------------------------
# projects_before is the list without fixtures-core: what an anonymous request
# sees while that private project exists.

def test_absent_deletes_the_project_an_anonymous_answer_left_out(server, run_module):
    private_project(server, 'projects_before', 'projects_with_created')
    locked_once(server)
    result = run_module(project.main, dict(name=NAME, state='absent', confirm_delete=True))
    assert result['changed'] is True
    assert len(server.calls('DELETE', '/projects/%d' % pid(server))) == 1
    assert len(server.calls('GET', '/projects')) == 2
    assert len(lock_waits()) == 1


def test_absent_fails_when_harbor_stays_anonymous(server, run_module):
    private_project(server, 'projects_before')
    locked_for_good(server)
    result = run_module(project.main, dict(name=NAME, state='absent', confirm_delete=True))
    assert result['failed'] is True
    assert 'stopped accepting the credentials' in result['msg']
    assert 'changed' not in result or result['changed'] is False
    assert server.calls('DELETE') == []
    assert len(lock_waits()) == 1


def test_absent_project_is_believed_after_one_login_check(server, run_module):
    private_project(server, 'projects_before')
    result = run_module(project.main, dict(name=NAME, state='absent'))
    assert result['changed'] is False
    assert len(server.calls('GET', '/projects')) == 1
    assert len(server.calls('GET', '/systeminfo')) == 2
    assert lock_waits() == []


# -- project: state present ----------------------------------------------------

def test_present_does_not_create_the_project_an_anonymous_answer_left_out(server, run_module):
    private_project(server, 'projects_before', 'projects_with_created')
    locked_once(server)
    result = run_module(project.main, dict(name=NAME))
    assert result.get('failed') is not True
    assert result['changed'] is False
    assert result['project']['project_id'] == pid(server)
    assert server.calls('POST') == []
    assert len(lock_waits()) == 1


def test_present_fails_when_harbor_stays_anonymous(server, run_module):
    private_project(server, 'projects_before')
    locked_for_good(server)
    result = run_module(project.main, dict(name=NAME))
    assert result['failed'] is True
    assert 'stopped accepting the credentials' in result['msg']
    assert server.calls('POST') == []


def test_present_fails_when_every_read_meets_a_lock(server, run_module):
    private_project(server, 'projects_before')
    login(server, 'systeminfo_anonymous', 'systeminfo', 'systeminfo_anonymous', 'systeminfo')
    result = run_module(project.main, dict(name=NAME))
    assert result['failed'] is True
    assert 'each of the 2 times' in result['msg'] and 'keeps failing to log in' in result['msg']
    assert server.calls('POST') == []
    assert len(server.calls('GET', '/projects')) == 2
    assert len(lock_waits()) == 2


def test_present_creates_after_one_login_check(server, run_module):
    private_project(server, 'projects_before')
    result = run_module(project.main, dict(name=NAME))
    assert result['changed'] is True
    assert len(server.calls('POST', '/projects')) == 1
    assert len(server.calls('GET', '/projects')) == 1
    assert len(server.calls('GET', '/systeminfo')) == 2


def test_a_project_that_is_found_costs_no_login_check(server, run_module):
    private_project(server, 'projects_with_created')
    result = run_module(project.main, dict(name=NAME))
    assert result['changed'] is False
    assert len(server.calls('GET', '/projects')) == 1
    assert len(server.calls('GET', '/systeminfo')) == 1
    assert server.calls('GET', '/projects')[0]['query']['name'] == [NAME]


# -- a server too slow to rule a lock out ---------------------------------------

@pytest.fixture
def slow(mocker):
    """Every look at the clock is 2 s after the one before: longer than a login lock."""
    mocker.patch('time.monotonic', side_effect=itertools.count(0, 2).__next__)


def test_slow_server_reads_again_and_finds_the_project(server, run_module, slow):
    private_project(server, 'projects_before', 'projects_with_created')
    result = run_module(project.main, dict(name=NAME))
    assert result['changed'] is False
    assert server.calls('POST') == []
    assert len(server.calls('GET', '/projects')) == 2
    assert lock_waits() == []


def test_slow_server_still_creates_a_project_that_is_missing_twice(server, run_module, slow):
    private_project(server, 'projects_before')
    result = run_module(project.main, dict(name=NAME))
    assert result['changed'] is True
    assert len(server.calls('POST', '/projects')) == 1
    assert len(server.calls('GET', '/projects')) == 2
    assert len(server.calls('GET', '/systeminfo')) == 3


# -- project_info ----------------------------------------------------------------

def test_info_lists_again_after_a_lock(server, run_module):
    private_project(server, 'projects_before', 'projects_with_created')
    locked_once(server)
    result = run_module(project_info.main, {})
    assert sorted(p['name'] for p in result['projects']) == [NAME, 'library']
    assert len(server.calls('GET', '/projects')) == 2
    assert len(lock_waits()) == 1


def test_info_fails_when_harbor_stays_anonymous(server, run_module):
    private_project(server, 'projects_before')
    locked_for_good(server)
    result = run_module(project_info.main, {})
    assert result['failed'] is True
    assert 'stopped accepting the credentials' in result['msg']
    assert 'projects' not in result


def test_info_list_costs_one_login_check(server, run_module):
    private_project(server, 'projects_with_created')
    result = run_module(project_info.main, {})
    assert len(result['projects']) == 2
    assert len(server.calls('GET', '/projects')) == 1
    assert len(server.calls('GET', '/systeminfo')) == 2
    assert lock_waits() == []


def test_info_of_a_named_project_that_is_found_costs_none(server, run_module):
    private_project(server, 'projects_with_created')
    result = run_module(project_info.main, dict(name=NAME))
    assert [p['name'] for p in result['projects']] == [NAME]
    assert len(server.calls('GET', '/systeminfo')) == 1


def test_info_of_a_named_project_an_anonymous_answer_left_out(server, run_module):
    private_project(server, 'projects_before', 'projects_with_created')
    locked_once(server)
    result = run_module(project_info.main, dict(name=NAME))
    assert [p['name'] for p in result['projects']] == [NAME]


def test_info_of_a_named_project_that_is_missing(server, run_module):
    private_project(server, 'projects_before')
    result = run_module(project_info.main, dict(name=NAME))
    assert result['projects'] == []
    assert len(server.calls('GET', '/systeminfo')) == 2


# -- the modules that work inside a project ---------------------------------------
# All of them find the project with require_project().

def webhook_routes(server):
    server.route('GET', '/projects/%d/webhook/policies' % server.fixtures['webhook_projects']['body'][0]['project_id'],
                 'webhook_list_one')


def robot_routes(server):
    server.route('GET', '/robots', 'robot_list_project')
    server.route('GET', '/configurations', 'robot_configurations')


def tag_routes(server):
    project_id = int(server.fixtures['tag_project_create']['headers']['location'].rsplit('/', 1)[-1])
    server.route('GET', '/projects/%d' % project_id, 'tag_project_get')
    server.route('GET', '/projects/%d/immutabletagrules' % project_id, 'tag_immutability_list_empty')


# (module, its arguments, the recorded project list, the routes it needs after the project is found)
SCOPED = [
    (webhook_info, dict(project='fixtures-webhook'), 'webhook_projects', webhook_routes),
    (webhook, dict(project='fixtures-webhook', name='no-such-hook', state='absent'), 'webhook_projects', webhook_routes),
    (robot_account_info, dict(project='fixtures-robot'), 'robot_projects_by_name', robot_routes),
    (robot_account, dict(level='project', project='fixtures-robot', name='no-such-robot', state='absent'),
     'robot_projects_by_name', robot_routes),
    (tag_retention_info, dict(project='fixtures-tag-policy'), 'tag_projects_list', tag_routes),
    (tag_immutability_info, dict(project='fixtures-tag-policy'), 'tag_projects_list', tag_routes),
]
IDS = ['webhook_info', 'webhook', 'robot_account_info', 'robot_account', 'tag_retention_info', 'tag_immutability_info']


@pytest.mark.parametrize('module, args, listing, routes', SCOPED, ids=IDS)
def test_scoped_module_finds_its_project_with_one_read(server, run_module, module, args, listing, routes):
    server.route('GET', '/projects', listing)
    routes(server)
    result = run_module(module.main, args)
    assert result.get('failed') is not True
    assert result['changed'] is False
    listed = server.calls('GET', '/projects')
    assert len(listed) == 1 and listed[0]['query']['name'] == [args['project']]
    assert len(server.calls('GET', '/systeminfo')) == 1


@pytest.mark.parametrize('module, args, listing, routes', SCOPED, ids=IDS)
def test_scoped_module_reads_again_after_a_lock(server, run_module, module, args, listing, routes):
    server.route('GET', '/projects', dict(NO_PROJECTS), listing)
    routes(server)
    locked_once(server)
    result = run_module(module.main, args)
    assert result.get('failed') is not True
    assert len(server.calls('GET', '/projects')) == 2
    assert len(lock_waits()) == 1


@pytest.mark.parametrize('module, args, listing, routes', SCOPED, ids=IDS)
def test_scoped_module_fails_when_harbor_stays_anonymous(server, run_module, module, args, listing, routes):
    server.route('GET', '/projects', dict(NO_PROJECTS))
    locked_for_good(server)
    result = run_module(module.main, args)
    assert result['failed'] is True
    assert 'stopped accepting the credentials' in result['msg']
    assert 'does not exist' not in result['msg']


@pytest.mark.parametrize('module, args, listing, routes', SCOPED, ids=IDS)
def test_scoped_module_still_says_a_missing_project_is_missing(server, run_module, module, args, listing, routes):
    server.route('GET', '/projects', dict(NO_PROJECTS))
    result = run_module(module.main, args)
    assert result['failed'] is True
    assert 'Project %r does not exist' % args['project'] in result['msg']
    assert len(server.calls('GET', '/projects')) == 1
    assert len(server.calls('GET', '/systeminfo')) == 2
    assert lock_waits() == []
