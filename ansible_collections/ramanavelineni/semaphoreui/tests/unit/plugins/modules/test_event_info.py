# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest
import yaml

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import event_info

PROJECT = 'ev-fixtures'


def pid(server):
    return server.fixtures['event_projects']['body'][0]['id']


@pytest.fixture
def base(server):
    server.route('GET', '/projects', 'event_projects')
    path = '/project/%d' % pid(server)
    server.route('GET', path + '/events/last', 'events_project_last')
    server.route('GET', path + '/events', 'events_project')
    server.route('GET', '/events/last', 'events_last')
    server.route('GET', '/events', 'events')
    return path


def asked(server):
    return [r['path'] for r in server.requests if 'events' in r['path']]


def test_events_of_a_project_newest_first(server, base, run_module):
    result = run_module(event_info.main, dict(project=PROJECT))
    assert result['changed'] is False
    events = result['events']
    assert len(events) == len(server.fixtures['events_project_last']['body']) == 3
    assert [e['created'] for e in events] == sorted((e['created'] for e in events), reverse=True)
    assert set(e['project'] for e in events) == set([PROJECT])
    assert set(e['project_id'] for e in events) == set([pid(server)])
    assert set(e['username'] for e in events) == set(['admin'])
    assert sorted(e['object_type'] for e in events) == ['key', 'project', 'repository']
    assert asked(server) == [base + '/events/last']


def test_an_event_in_the_documented_form(server, base, run_module):
    newest = run_module(event_info.main, dict(project=PROJECT))['events'][0]
    recorded = server.fixtures['events_project_last']['body'][0]
    assert newest == dict(
        created=newest['created'], description=recorded['description'], object_type=recorded['object_type'],
        object_id=recorded['object_id'], object_name=recorded['object_name'], project_id=pid(server),
        project=PROJECT, user_id=recorded['user_id'], username='admin', integration_id=None)
    # The time is the server's, in UTC, cut to the microseconds a comparison can use.
    assert newest['created'].endswith('Z') and newest['created'][:19] == recorded['created'][:19]
    documented = yaml.safe_load(event_info.RETURN)['events']['contains']
    assert set(newest) == set(documented)


@pytest.mark.parametrize('limit, path, count', [
    (1, '/events/last', 1),
    (2, '/events/last', 2),
    (200, '/events/last', 3),
    (201, '/events', 3),
    (0, '/events', 3),
])
def test_limit_picks_the_list_and_cuts_it(server, base, run_module, limit, path, count):
    result = run_module(event_info.main, dict(project=PROJECT, limit=limit))
    assert len(result['events']) == count
    assert asked(server) == [base + path]
    assert result['events'] == run_module(event_info.main, dict(project=PROJECT, limit=0))['events'][:count]


def test_without_a_project_the_lists_across_projects_are_read(server, base, run_module):
    result = run_module(event_info.main, {})
    assert asked(server) == ['/events/last']
    assert server.calls('GET', '/projects') == []
    assert result['events'] == run_module(event_info.main, dict(project=PROJECT))['events']
    del server.requests[:]
    run_module(event_info.main, dict(limit=0))
    assert asked(server) == ['/events']


def test_by_project_id(server, base, run_module):
    server.route('GET', base, dict(status=200, body=server.fixtures['event_projects']['body'][0]))
    del server.routes[('GET', '/projects')]
    result = run_module(event_info.main, dict(project_id=pid(server)))
    assert len(result['events']) == 3


def test_an_event_about_nothing_in_particular(server, base, run_module):
    # Hand-edited: an event without object, project and user, as Semaphore writes for some of its own actions.
    listing = server.response('events_last')
    listing['body'] = [dict(listing['body'][0], object_id=None, object_type=None, object_name='', project_id=None,
                            project_name=None, user_id=None, username=None, description=None)]
    server.route('GET', '/events/last', listing)
    event = run_module(event_info.main, {})['events'][0]
    assert (event['object_type'], event['object_id'], event['object_name'], event['description']) == ('', None, '', '')
    assert (event['project'], event['project_id'], event['user_id'], event['username']) == (None, None, None, None)


def test_no_events(server, base, run_module):
    server.route('GET', '/events/last', dict(status=200, body=[]))
    assert run_module(event_info.main, {})['events'] == []
    # Hand-written: Go writes an empty list as null in some answers.
    server.route('GET', '/events/last', dict(status=200, body=None))
    assert run_module(event_info.main, {})['events'] == []


def test_negative_limit_and_both_project_options_are_refused(server, run_module):
    result = run_module(event_info.main, dict(limit=-1))
    assert result['failed'] is True and 'limit must be 0 (every event) or more' in result['msg']
    both = run_module(event_info.main, dict(project=PROJECT, project_id=1))
    assert 'mutually exclusive' in both['msg']
    assert asked(server) == []


def test_missing_project_fails_in_check_mode_too(server, base, run_module):
    for check_mode in (False, True):
        result = run_module(event_info.main, dict(project='no-such-project'), check_mode=check_mode)
        assert result['failed'] is True and "Project 'no-such-project' does not exist" in result['msg']
    assert asked(server) == []


def test_check_mode_is_the_same(server, base, run_module):
    real = run_module(event_info.main, dict(project=PROJECT))
    checked = run_module(event_info.main, dict(project=PROJECT), check_mode=True)
    assert checked['events'] == real['events'] and checked['changed'] is False
    assert [r['method'] for r in server.requests if not r['path'].startswith('/auth/')] == ['GET'] * 6
    assert set(real) - set(['changed', 'invocation', 'warnings', 'deprecations']) == set(yaml.safe_load(event_info.RETURN))
