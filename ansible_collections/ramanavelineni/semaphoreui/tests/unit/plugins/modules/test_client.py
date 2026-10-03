# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""What the client hands to open_url, and when it sends a request again.

A change that stops verifying certificates, follows a redirect with the
credentials, or retries a create has to fail here.
"""

import time

from http.cookiejar import CookieJar

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils import semaphore
from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import info, project
from ansible_collections.ramanavelineni.semaphoreui.tests.unit.plugins.conftest import (
    PATCH_TARGET,
    FakeResponse,
    transport_error,
)

CONNECTION_ENV = ('SEMAPHORE_URL', 'SEMAPHORE_API_TOKEN', 'SEMAPHORE_USERNAME', 'SEMAPHORE_PASSWORD',
                  'SEMAPHORE_VALIDATE_CERTS', 'SEMAPHORE_CA_PATH')


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """The machine running the tests may have its own SEMAPHORE_* variables."""
    for name in CONNECTION_ENV:
        monkeypatch.delenv(name, raising=False)


def unavailable(status=503):
    return dict(status=status, body=None)


def pid(server):
    return server.fixtures['projects_one']['body'][0]['id']


@pytest.fixture
def urls(server, mocker):
    """The URL of every request, in order (the fake server keeps only the path)."""
    seen = []

    def open_url(url, **kwargs):
        seen.append(url)
        return server(url, **kwargs)

    mocker.patch(PATCH_TARGET, side_effect=open_url)
    return seen


def waits():
    return [call.args[0] for call in time.sleep.call_args_list]


def answer_html(server, mocker, method, path):
    """Answer one route with a page instead of JSON, as a proxy or a login page would.

    The fake server can only answer with JSON, so this sits in front of it.
    """
    page = FakeResponse(200, None)
    page.raw = b'<html><body>Sign in</body></html>'

    def open_url(url, **kwargs):
        if kwargs.get('method') == method and url.endswith('/api' + path):
            server.requests.append(dict(method=method, path=path, headers=kwargs.get('headers') or {},
                                        body=None, kwargs=kwargs))
            return page
        return server(url, **kwargs)

    mocker.patch(PATCH_TARGET, side_effect=open_url)


# -- what reaches open_url -----------------------------------------------------

def test_defaults_reach_every_request(server, run_module):
    result = run_module(info.main, {})
    assert result.get('failed') is not True
    # Login, the reads and the logout: none may differ.
    assert [r['path'] for r in server.requests] == ['/auth/login', '/info', '/apps', '/auth/logout']
    for request in server.requests:
        kwargs = request['kwargs']
        assert kwargs['validate_certs'] is True
        assert kwargs['ca_path'] is None
        assert kwargs['timeout'] == 30
        assert kwargs['follow_redirects'] == 'none'
        assert kwargs['use_netrc'] is False
        assert kwargs['use_proxy'] is True


def test_options_reach_every_request(server, run_module):
    run_module(info.main, dict(validate_certs=False, ca_path='/etc/ssl/step-root.pem', timeout=7))
    assert len(server.requests) == 4
    for request in server.requests:
        kwargs = request['kwargs']
        assert kwargs['validate_certs'] is False
        assert kwargs['ca_path'] == '/etc/ssl/step-root.pem'
        assert kwargs['timeout'] == 7


def test_session_cookies_are_shared_by_the_requests_of_a_run(server, run_module):
    run_module(info.main, {})
    jars = [r['kwargs']['cookies'] for r in server.requests]
    assert isinstance(jars[0], CookieJar)
    assert all(jar is jars[0] for jar in jars)


def test_requests_go_to_the_configured_server(server, run_module, urls):
    run_module(info.main, dict(url='https://semaphore.example.com/api/'))
    assert len(server.requests) == 4
    assert urls == ['https://semaphore.example.com/api' + r['path'] for r in server.requests]


def test_a_redirect_is_an_error_not_followed(server, run_module):
    # With follow_redirects='none' open_url raises on a 3xx instead of
    # sending the credentials to wherever it points.
    server.route('GET', '/info', dict(status=302, body=None))
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert 'returned HTTP 302' in result['msg']
    assert len(server.calls('GET', '/info')) == 1
    assert waits() == []


# -- retries -------------------------------------------------------------------

@pytest.mark.parametrize('status', semaphore.RETRY_STATUSES)
def test_reads_are_retried_after_a_gateway_status(server, run_module, status):
    server.route('GET', '/info', unavailable(status), 'info')
    result = run_module(info.main, dict(retry_delay=5))
    assert result.get('failed') is not True
    assert len(server.calls('GET', '/info')) == 2
    assert waits() == [5]


def test_retry_statuses_are_the_gateway_ones():
    assert semaphore.RETRY_STATUSES == (502, 503, 504)


@pytest.mark.parametrize('status', [400, 404, 500])
def test_other_statuses_are_not_retried(server, run_module, status):
    server.route('GET', '/info', unavailable(status))
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert result['request_details']['status'] == status
    assert len(server.calls('GET', '/info')) == 1
    assert waits() == []


def test_read_retries_run_out(server, run_module):
    server.route('GET', '/info', unavailable())
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert result['request_details']['status'] == 503
    # The first attempt and the default of three retries, two seconds apart.
    assert len(server.calls('GET', '/info')) == 4
    assert waits() == [2, 2, 2]
    assert server.requests[-1]['path'] == '/auth/logout'


def test_transport_retries_run_out(server, run_module):
    server.route('GET', '/info', transport_error())
    result = run_module(info.main, dict(retries=1))
    assert result['failed'] is True
    assert 'without an HTTP response' in result['msg']
    assert 'connection reset by peer' in result['msg']
    assert len(server.calls('GET', '/info')) == 2


@pytest.mark.parametrize('retries', [0, -1])
def test_no_retries(server, run_module, retries):
    server.route('GET', '/info', unavailable(), 'info')
    result = run_module(info.main, dict(retries=retries))
    assert result['failed'] is True
    assert len(server.calls('GET', '/info')) == 1
    assert waits() == []


def test_updates_are_retried(server, run_module):
    # A PUT carries the whole object, so sending it twice ends the same.
    server.route('GET', '/projects', 'projects_one')
    server.route('PUT', '/project/%d' % pid(server), unavailable(), transport_error(), 'project_update')
    result = run_module(project.main, dict(name='homelab', alert=True))
    assert result['changed'] is True
    puts = server.calls('PUT')
    assert len(puts) == 3
    assert puts[0]['body'] == puts[1]['body'] == puts[2]['body']


def test_creates_are_not_retried_after_a_gateway_status(server, run_module):
    # The server may have created the object before the proxy gave up.
    server.route('GET', '/projects', 'projects_empty')
    server.route('POST', '/projects', unavailable(), 'project_create')
    result = run_module(project.main, dict(name='homelab'))
    assert result['failed'] is True
    assert result['request_details']['status'] == 503
    assert len(server.calls('POST', '/projects')) == 1
    assert waits() == []


def test_deletes_are_not_retried(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    server.route('DELETE', '/project/%d' % pid(server), unavailable(), 'project_delete')
    result = run_module(project.main, dict(name='homelab', state='absent', confirm_delete=True))
    assert result['failed'] is True
    assert len(server.calls('DELETE')) == 1


def test_login_is_retried(server, run_module):
    server.route('POST', '/auth/login', unavailable(), 'login')
    result = run_module(info.main, {})
    assert result.get('failed') is not True
    assert len(server.calls('POST', '/auth/login')) == 2


def test_failed_logout_is_not_retried_and_does_not_fail_the_task(server, run_module):
    server.route('POST', '/auth/logout', unavailable())
    result = run_module(info.main, {})
    assert result.get('failed') is not True
    assert len(server.calls('POST', '/auth/logout')) == 1


# -- answers that are not JSON -------------------------------------------------

def test_a_body_that_is_not_json_fails_with_the_body(server, run_module, mocker):
    answer_html(server, mocker, 'GET', '/info')
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert 'response is not JSON' in result['msg']
    assert 'Sign in' in result['msg']
    assert result['request_details']['status'] == 200
    assert 'exception' not in result
    # Not retried: the server answered.
    assert len(server.calls('GET', '/info')) == 1
    assert server.requests[-1]['path'] == '/auth/logout'


# -- environment ---------------------------------------------------------------

def test_url_from_the_environment(run_module, monkeypatch, urls):
    monkeypatch.setenv('SEMAPHORE_URL', 'https://from-env.example.com')
    result = run_module(info.main, dict(url=None))
    assert result.get('failed') is not True
    assert urls[0] == 'https://from-env.example.com/api/auth/login'


def test_url_is_required(server, run_module):
    result = run_module(info.main, dict(url=None))
    assert result['failed'] is True
    assert 'url' in result['msg']
    assert server.requests == []


def test_url_option_wins_over_the_environment(run_module, monkeypatch, urls):
    monkeypatch.setenv('SEMAPHORE_URL', 'https://from-env.example.com')
    run_module(info.main, {})
    assert urls[0] == 'https://semaphore.example.com/api/auth/login'


@pytest.mark.parametrize('value, expected', [('false', False), ('no', False), ('0', False), ('true', True)])
def test_validate_certs_from_the_environment(server, run_module, monkeypatch, value, expected):
    monkeypatch.setenv('SEMAPHORE_VALIDATE_CERTS', value)
    run_module(info.main, {})
    assert len(server.requests) == 4
    assert all(r['kwargs']['validate_certs'] is expected for r in server.requests)


def test_validate_certs_option_wins_over_the_environment(server, run_module, monkeypatch):
    monkeypatch.setenv('SEMAPHORE_VALIDATE_CERTS', 'false')
    run_module(info.main, dict(validate_certs=True))
    assert len(server.requests) == 4
    assert all(r['kwargs']['validate_certs'] is True for r in server.requests)


def test_ca_path_from_the_environment(server, run_module, monkeypatch):
    monkeypatch.setenv('SEMAPHORE_CA_PATH', '/etc/ssl/from-env.pem')
    run_module(info.main, {})
    assert len(server.requests) == 4
    assert all(r['kwargs']['ca_path'] == '/etc/ssl/from-env.pem' for r in server.requests)


def test_ca_path_option_wins_over_the_environment(server, run_module, monkeypatch):
    monkeypatch.setenv('SEMAPHORE_CA_PATH', '/etc/ssl/from-env.pem')
    run_module(info.main, dict(ca_path='/etc/ssl/step-root.pem'))
    assert all(r['kwargs']['ca_path'] == '/etc/ssl/step-root.pem' for r in server.requests)
