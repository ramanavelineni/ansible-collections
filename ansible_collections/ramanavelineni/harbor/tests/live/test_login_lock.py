# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Harbor's login lock, and what the modules make of the answers it causes.

After a failed login Harbor locks that user name for a moment. While the lock
holds, requests for the user are handled as anonymous even with the right
password: /systeminfo answers without harbor_version, /projects answers 200
with the public projects only, and what needs a login answers 401. A module
that believed such a /projects answer would take a private project for
missing. The client checks the login again before it believes "not there".

The lock is provoked on a user of the suite's own, never on the administrator.
"""

import threading
import time

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils import harbor
from ansible_collections.ramanavelineni.harbor.plugins.modules import project as project_module
from ansible_collections.ramanavelineni.harbor.plugins.modules import project_info, webhook_info
from ansible_collections.ramanavelineni.harbor.tests.live.conftest import changed, wait_out_lock

WRONG = 'Not-The-Password-1'
# A request with the right password that takes longer than this is no use for timing a lock.
SLOW = 0.3


def anonymous(api, member):
    """Whether Harbor answers the member's request, sent with the right password, as for nobody."""
    status, info, dummy = api.call('GET', '/systeminfo', **member)
    return status == 200 and 'harbor_version' not in info


def begin_lock(api, member):
    """Fail one login as the member; back once Harbor answers the member anonymously.

    Returns the thread of the failed login, which Harbor answers only when
    the lock is over, and the times the login was sent and the lock was seen.
    """
    sent = time.monotonic()
    failing = threading.Thread(target=api.call, args=('GET', '/users/current'),
                               kwargs=dict(username=member['username'], password=WRONG))
    failing.start()
    while time.monotonic() - sent < 20:
        if anonymous(api, member):
            return failing, sent, time.monotonic()
        time.sleep(0.01)
    failing.join()
    pytest.fail('Harbor never answered %s anonymously after a failed login: no lock was seen' % member['username'])


@pytest.fixture
def locked_run(api, run, member, monkeypatch):
    """locked_run(main, args): run a module as the member, with a lock that begins right after its login check.

    Returns the result and what the client's later login checks said
    ('held', 'locked' or 'unsure'), in order.
    """
    original_check = harbor.HarborClient.check_login
    original_recheck = harbor.HarborClient.recheck_login
    seen = dict(threads=[], states=[], armed=False, hidden=None)

    def check_then_lock(client):
        original_check(client)
        if seen['armed']:
            seen['armed'] = False
            failing, dummy, dummy = begin_lock(api, member)
            seen['threads'].append(failing)
            # What a lookup sent this moment gets: the private project is not in the answer.
            seen['hidden'] = api.call('GET', '/projects?name=%s' % seen['project'], **member)

    def recheck(client):
        state = original_recheck(client)
        seen['states'].append(state)
        return state

    monkeypatch.setattr(harbor.HarborClient, 'check_login', check_then_lock)
    monkeypatch.setattr(harbor.HarborClient, 'recheck_login', recheck)

    def call(main, args, project, check=False):
        del seen['states'][:]
        seen['armed'] = True
        seen['project'] = project
        result = run(main, dict(member, **args), check=check)
        hidden = seen['hidden']
        status, body = hidden[0], hidden[1]
        assert status == 200 and body == [], 'the lookup was not answered anonymously: %s %s' % (status, body)
        states = list(seen['states'])
        for thread in seen['threads']:
            thread.join()
        del seen['threads'][:]
        wait_out_lock()
        return result, states

    yield call
    for thread in seen['threads']:
        thread.join()
    wait_out_lock()


def test_what_harbor_answers_during_the_lock(api, project, member, record_property):
    """The facts the client builds on, and how long the lock lasts."""
    pid = api.projects(project)[0]['project_id']
    assert not anonymous(api, member)

    failing, sent, first_seen = begin_lock(api, member)
    info = api.call('GET', '/systeminfo', **member)
    listing = api.call('GET', '/projects?name=%s' % project, **member)
    current = api.call('GET', '/users/current', **member)
    single = api.call('GET', '/projects/%d' % pid, **member)
    # The administrator is not locked by somebody else's failure.
    admin = api.call('GET', '/systeminfo')

    last_seen = first_seen
    while time.monotonic() - sent < 20:
        if not anonymous(api, member):
            break
        last_seen = time.monotonic()
        time.sleep(0.01)
    over = time.monotonic()
    failing.join()

    # Anonymous answers, although the password was right:
    assert info[0] == 200 and 'harbor_version' not in info[1]
    assert listing[0] == 200 and listing[1] == []
    assert current[0] == 401
    assert single[0] == 401
    assert 'harbor_version' in admin[1]
    # And afterwards the same requests are answered as the user again.
    assert [p['name'] for p in api.call('GET', '/projects?name=%s' % project, **member)[1]] == [project]

    record_property('lock_first_seen_after_failed_login_was_sent', round(first_seen - sent, 2))
    record_property('lock_last_seen_after_failed_login_was_sent', round(last_seen - sent, 2))
    record_property('lock_seen_for', round(last_seen - first_seen, 2))
    print('login lock: failed login sent at 0.00, anonymous answers from %.2f to %.2f s, the user again at %.2f s'
          % (first_seen - sent, last_seen - sent, over - sent))
    # The client waits LOGIN_LOCK_WAIT after an anonymous answer and then asks again. That only works
    # when no lock outlasts the wait.
    assert last_seen - first_seen < harbor.LOGIN_LOCK_WAIT


def test_a_run_that_starts_inside_the_lock_waits_it_out(api, run, project, member):
    failing, dummy, dummy = begin_lock(api, member)
    found = run(project_info.main, dict(member, name=project))
    failing.join()
    wait_out_lock()
    assert not found.get('failed'), found.get('msg')
    assert [p['name'] for p in found['projects']] == [project]


def test_project_present_is_not_created_again(locked_run, project):
    """Without the second login check: the project looks missing, a create is sent, Harbor answers 409."""
    result, states = locked_run(project_module.main, dict(name=project, public=False), project)
    assert changed(result) is False
    assert result['project']['name'] == project
    assert states and states[0] in (harbor.LOCKED, harbor.UNSURE)


def test_project_info_does_not_leave_the_private_project_out(locked_run, project):
    result, states = locked_run(project_info.main, dict(name=project), project)
    assert not result.get('failed'), result.get('msg')
    assert [p['name'] for p in result['projects']] == [project]
    assert states and states[0] in (harbor.LOCKED, harbor.UNSURE)


def test_a_project_scoped_module_finds_its_project(locked_run, project):
    """Without the second login check: "Project ... does not exist"."""
    result, states = locked_run(webhook_info.main, dict(project=project), project)
    assert not result.get('failed'), result.get('msg')
    assert result['webhooks'] == []
    assert states and states[0] in (harbor.LOCKED, harbor.UNSURE)


def test_project_absent_deletes_the_project(api, locked_run, project):
    """Without the second login check: "no change", and the project stays."""
    result, states = locked_run(project_module.main, dict(name=project, state='absent', confirm_delete=True), project)
    assert changed(result) is True
    assert api.projects(project) == []
    assert states and states[0] in (harbor.LOCKED, harbor.UNSURE)


def test_a_user_who_stays_locked_fails_the_task(api, run, project, member):
    """Another client that keeps failing to log in: the task fails and says why, instead of deciding on what it saw.

    Only where logging in is quick: there, failed logins sent one after the
    other keep the user locked without a gap. Where every login takes a
    second (Harbor 2.15 hashes the password on each request), they do not.
    """
    began = time.monotonic()
    api.ok('GET', '/systeminfo', **member)
    if time.monotonic() - began > SLOW:
        pytest.skip('logging in takes %.1f s on this server: failed logins cannot keep a user locked without gaps'
                    % (time.monotonic() - began))

    stop = threading.Event()

    def keep_failing():
        while not stop.is_set():
            api.call('GET', '/users/current', username=member['username'], password=WRONG)

    failing = threading.Thread(target=keep_failing)
    failing.start()
    try:
        deadline = time.monotonic() + 20
        while not anonymous(api, member) and time.monotonic() < deadline:
            time.sleep(0.01)
        result = run(project_info.main, dict(member, name=project))
    finally:
        stop.set()
        failing.join()
        wait_out_lock()
    assert result.get('failed') is True
    assert 'anonymous' in result['msg']
    assert 'exception' not in result
