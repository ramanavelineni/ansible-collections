# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""What the client hands to open_url, and when it sends a request again.

A change that stops verifying certificates, follows a redirect with the
credentials, or retries a create has to fail here. The one retry after a 401
is in test_login_lock.py.
"""

import base64
import json
import socket
import ssl
import time
from urllib.error import URLError

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils import harbor
from ansible_collections.ramanavelineni.harbor.plugins.modules import info, project, project_info
from ansible_collections.ramanavelineni.harbor.tests.unit.plugins.conftest import (
    PATCH_TARGET,
    FakeResponse,
    transport_error,
)

CONNECTION_ENV = ('HARBOR_URL', 'HARBOR_USERNAME', 'HARBOR_PASSWORD', 'HARBOR_VALIDATE_CERTS', 'HARBOR_CA_PATH',
                  'HARBOR_WARN_UNTESTED_VERSION')


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """The machine running the tests may have its own HARBOR_* variables."""
    for name in CONNECTION_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def urls(server, mocker):
    """The URL of every request, in order (the fake server keeps only the path)."""
    seen = []

    def open_url(url, **kwargs):
        seen.append(url)
        return server(url, **kwargs)

    mocker.patch(PATCH_TARGET, side_effect=open_url)
    return seen


def unavailable(status=503):
    return dict(status=status, body=None)


def basic(username, password):
    return 'Basic ' + base64.b64encode(('%s:%s' % (username, password)).encode()).decode()


def pid(server):
    return int(server.fixtures['project_create']['headers']['location'].rsplit('/', 1)[-1])


def existing(server):
    server.route('GET', '/projects', 'projects_with_created')
    server.route('GET', '/registries', 'registries_empty')
    server.route('GET', '/quotas', 'quotas_created')


def waits():
    return [call.args[0] for call in time.sleep.call_args_list]


def answer_html(server, mocker, method, path):
    """Answer one route with a page instead of JSON, as a proxy or a login page would.

    The fake server can only answer with JSON, so this sits in front of it.
    """
    page = FakeResponse(200, None, {'content-type': 'text/html'})
    page.raw = b'<html><body>Sign in</body></html>'

    def open_url(url, **kwargs):
        if kwargs.get('method') == method and url.split('?')[0].endswith('/api/v2.0' + path):
            server.requests.append(dict(method=method, path=path, query={}, headers=kwargs.get('headers') or {},
                                        body=None, kwargs=kwargs))
            return page
        return server(url, **kwargs)

    mocker.patch(PATCH_TARGET, side_effect=open_url)


# -- what reaches open_url -----------------------------------------------------

def test_defaults_reach_every_request(server, run_module):
    existing(server)
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result.get('failed') is not True
    # The login check and the reads: none may differ.
    assert len(server.requests) > 1
    for request in server.requests:
        kwargs = request['kwargs']
        assert kwargs['validate_certs'] is True
        assert kwargs['ca_path'] is None
        assert kwargs['timeout'] == 30
        assert kwargs['follow_redirects'] == 'none'
        assert kwargs['use_netrc'] is False
        assert kwargs['use_proxy'] is True


def test_options_reach_every_request(server, run_module):
    existing(server)
    run_module(project.main, dict(name='fixtures-core', validate_certs=False, ca_path='/etc/ssl/step-root.pem',
                                  timeout=7))
    assert len(server.requests) > 1
    for request in server.requests:
        kwargs = request['kwargs']
        assert kwargs['validate_certs'] is False
        assert kwargs['ca_path'] == '/etc/ssl/step-root.pem'
        assert kwargs['timeout'] == 7


def test_every_request_carries_the_credentials_as_basic_auth(server, run_module):
    existing(server)
    run_module(project.main, dict(name='fixtures-core'))
    assert len(server.requests) > 1
    assert all(r['headers']['Authorization'] == basic('admin', 's3cret-pw') for r in server.requests)


def test_requests_go_to_the_configured_server(run_module, urls):
    run_module(info.main, dict(url='https://harbor.example.com/api/v2.0/'))
    assert urls == ['https://harbor.example.com/api/v2.0/systeminfo']


def test_a_redirect_is_an_error_not_followed(server, run_module):
    # With follow_redirects='none' open_url raises on a 3xx instead of
    # sending the credentials to wherever it points.
    server.route('GET', '/systeminfo', dict(status=302, body=None))
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert 'returned HTTP 302' in result['msg']
    assert len(server.calls('GET', '/systeminfo')) == 1
    assert waits() == []


# -- retries -------------------------------------------------------------------

@pytest.mark.parametrize('status', harbor.RETRY_STATUSES)
def test_reads_are_retried_after_a_gateway_status(server, run_module, status):
    server.route('GET', '/systeminfo', unavailable(status), 'systeminfo')
    result = run_module(info.main, dict(retry_delay=5))
    assert result.get('failed') is not True
    assert len(server.calls('GET', '/systeminfo')) == 2
    assert waits() == [5]


def test_retry_statuses_are_the_gateway_ones():
    assert harbor.RETRY_STATUSES == (502, 503, 504)


@pytest.mark.parametrize('status', [400, 404, 500])
def test_other_statuses_are_not_retried(server, run_module, status):
    server.route('GET', '/systeminfo', unavailable(status))
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert result['request_details']['status'] == status
    assert len(server.calls('GET', '/systeminfo')) == 1
    assert waits() == []


def test_read_retries_run_out(server, run_module):
    server.route('GET', '/systeminfo', unavailable())
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert result['request_details']['status'] == 503
    # The first attempt and the default of three retries, two seconds apart.
    assert len(server.calls('GET', '/systeminfo')) == 4
    assert waits() == [2, 2, 2]


def test_transport_retries_run_out(server, run_module):
    server.route('GET', '/systeminfo', transport_error())
    result = run_module(info.main, dict(retries=1))
    assert result['failed'] is True
    assert 'without an HTTP response' in result['msg']
    assert 'connection reset by peer' in result['msg']
    assert len(server.calls('GET', '/systeminfo')) == 2


@pytest.mark.parametrize('retries', [0, -1])
def test_no_retries(server, run_module, retries):
    server.route('GET', '/systeminfo', unavailable(), 'systeminfo')
    result = run_module(info.main, dict(retries=retries))
    assert result['failed'] is True
    assert len(server.calls('GET', '/systeminfo')) == 1
    assert waits() == []


# What open_url raises for a setting that is wrong, built the way it arrives:
# urllib wraps a failed handshake and a failed name lookup in a URLError, and
# a ca_path that is not there comes straight from ssl.create_default_context.
def cannot_verify():
    return URLError(ssl.SSLCertVerificationError(
        1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate'))


def no_ca_file():
    return FileNotFoundError(2, 'No such file or directory')


def no_such_host():
    return URLError(socket.gaierror(socket.EAI_NONAME, 'nodename nor servname provided, or not known'))


def refused():
    return URLError(ConnectionRefusedError(61, 'Connection refused'))


def resolver_busy():
    return URLError(socket.gaierror(socket.EAI_AGAIN, 'Temporary failure in name resolution'))


@pytest.mark.parametrize('error, text', [
    (cannot_verify, 'CERTIFICATE_VERIFY_FAILED'),
    (no_ca_file, 'No such file or directory'),
    (no_such_host, 'nodename nor servname provided'),
], ids=['certificate', 'ca-file', 'host-name'])
def test_a_wrong_setting_is_not_retried(server, run_module, error, text):
    server.route('GET', '/systeminfo', error(), 'systeminfo')
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert 'without an HTTP response' in result['msg']
    assert text in result['msg']
    assert len(server.calls('GET', '/systeminfo')) == 1
    assert waits() == []


@pytest.mark.parametrize('error', [refused, resolver_busy, TimeoutError, transport_error],
                         ids=['refused', 'resolver-busy', 'timeout', 'reset'])
def test_a_passing_failure_is_retried(server, run_module, error):
    server.route('GET', '/systeminfo', error(), 'systeminfo')
    result = run_module(info.main, dict(retry_delay=5))
    assert result.get('failed') is not True
    assert len(server.calls('GET', '/systeminfo')) == 2
    assert waits() == [5]


def test_an_update_with_a_wrong_setting_is_not_retried(server, run_module):
    existing(server)
    path = '/projects/%d' % pid(server)
    server.route('PUT', path, cannot_verify(), 'project_update')
    result = run_module(project.main, dict(name='fixtures-core', public=True))
    assert result['failed'] is True
    assert len(server.calls('PUT', path)) == 1
    assert waits() == []


def test_updates_are_retried(server, run_module):
    # A PUT says what the object should be, so sending it twice ends the same.
    existing(server)
    path = '/projects/%d' % pid(server)
    server.route('PUT', path, unavailable(), transport_error(), 'project_update')
    result = run_module(project.main, dict(name='fixtures-core', public=True))
    assert result['changed'] is True
    puts = server.calls('PUT', path)
    assert len(puts) == 3
    assert puts[0]['body'] == puts[1]['body'] == puts[2]['body']


def test_creates_are_not_retried_after_a_gateway_status(server, run_module):
    # The server may have created the object before the proxy gave up.
    server.route('GET', '/projects', 'projects_before')
    server.route('POST', '/projects', unavailable(), 'project_create')
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result['failed'] is True
    assert result['request_details']['status'] == 503
    assert len(server.calls('POST', '/projects')) == 1
    assert waits() == []


def test_deletes_are_not_retried(server, run_module):
    existing(server)
    server.route('DELETE', '/projects/%d' % pid(server), unavailable(), 'project_delete')
    result = run_module(project.main, dict(name='fixtures-core', state='absent', confirm_delete=True))
    assert result['failed'] is True
    assert len(server.calls('DELETE')) == 1


# -- answers that are not JSON -------------------------------------------------

def test_a_body_that_is_not_json_fails_with_the_body(server, run_module, mocker):
    answer_html(server, mocker, 'GET', '/systeminfo')
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert 'response is not JSON' in result['msg']
    assert 'Sign in' in result['msg']
    assert result['request_details']['status'] == 200
    assert 'exception' not in result
    # Not retried: the server answered.
    assert len(server.calls('GET', '/systeminfo')) == 1


# -- environment ---------------------------------------------------------------

def test_url_and_credentials_from_the_environment(server, run_module, monkeypatch, urls):
    monkeypatch.setenv('HARBOR_URL', 'https://from-env.example.com')
    monkeypatch.setenv('HARBOR_USERNAME', 'env-user')
    monkeypatch.setenv('HARBOR_PASSWORD', 'env-s3cret')
    result = run_module(info.main, dict(url=None, username=None, password=None))
    assert result.get('failed') is not True
    assert urls == ['https://from-env.example.com/api/v2.0/systeminfo']
    assert server.requests[0]['headers']['Authorization'] == basic('env-user', 'env-s3cret')


@pytest.mark.parametrize('missing', ['url', 'username', 'password'])
def test_connection_options_are_required(server, run_module, missing):
    result = run_module(info.main, {missing: None})
    assert result['failed'] is True
    assert missing in result['msg']
    assert server.requests == []


def test_options_win_over_the_environment(server, run_module, monkeypatch, urls):
    monkeypatch.setenv('HARBOR_URL', 'https://from-env.example.com')
    monkeypatch.setenv('HARBOR_USERNAME', 'env-user')
    monkeypatch.setenv('HARBOR_PASSWORD', 'env-s3cret')
    run_module(info.main, {})
    assert urls == ['https://harbor.example.com/api/v2.0/systeminfo']
    assert server.requests[0]['headers']['Authorization'] == basic('admin', 's3cret-pw')


@pytest.mark.parametrize('value, expected', [('false', False), ('no', False), ('0', False), ('true', True)])
def test_validate_certs_from_the_environment(server, run_module, monkeypatch, value, expected):
    monkeypatch.setenv('HARBOR_VALIDATE_CERTS', value)
    run_module(info.main, {})
    assert len(server.requests) == 1
    assert server.requests[0]['kwargs']['validate_certs'] is expected


def test_validate_certs_option_wins_over_the_environment(server, run_module, monkeypatch):
    monkeypatch.setenv('HARBOR_VALIDATE_CERTS', 'false')
    run_module(info.main, dict(validate_certs=True))
    assert len(server.requests) == 1
    assert server.requests[0]['kwargs']['validate_certs'] is True


def test_ca_path_from_the_environment(server, run_module, monkeypatch):
    monkeypatch.setenv('HARBOR_CA_PATH', '/etc/ssl/from-env.pem')
    run_module(info.main, {})
    assert len(server.requests) == 1
    assert server.requests[0]['kwargs']['ca_path'] == '/etc/ssl/from-env.pem'


def test_ca_path_option_wins_over_the_environment(server, run_module, monkeypatch):
    monkeypatch.setenv('HARBOR_CA_PATH', '/etc/ssl/from-env.pem')
    run_module(info.main, dict(ca_path='/etc/ssl/step-root.pem'))
    assert len(server.requests) == 1
    assert server.requests[0]['kwargs']['ca_path'] == '/etc/ssl/step-root.pem'


# -- paged lists ---------------------------------------------------------------

class StubModule(object):
    """What HarborClient reads from a module, for calling list() on its own."""

    no_log_values = set()

    def __init__(self):
        self.params = dict(url='https://harbor.example.com', username='admin', password='s3cret-pw',
                           validate_certs=True, ca_path=None, timeout=30, retries=3, retry_delay=2,
                           warn_untested_version=True)


def page(count, total=None, first=0):
    """A list answer of `count` items, hand-written: no recorded list is longer than two."""
    headers = {} if total is None else {'x-total-count': str(total)}
    return dict(status=200, body=[dict(id=first + n) for n in range(count)], headers=headers)


def pages_asked(server, path):
    return [call['query']['page'] for call in server.calls('GET', path)]


def test_list_reads_one_page_when_it_holds_everything(server):
    server.route('GET', '/projects', 'projects_with_created')
    items = harbor.HarborClient(StubModule()).list('/projects')
    assert items == server.fixtures['projects_with_created']['body']
    assert pages_asked(server, '/projects') == [['1']]
    assert server.calls('GET', '/projects')[0]['query']['page_size'] == ['100']


def test_list_stops_at_a_full_page_that_is_the_total(server):
    server.route('GET', '/things', page(100, total=100))
    assert len(harbor.HarborClient(StubModule()).list('/things')) == 100
    assert pages_asked(server, '/things') == [['1']]


def test_list_follows_the_total_past_a_short_page(server):
    # A proxy that caps the page size at 2: no page is full, the total says there is more.
    server.route('GET', '/things', page(2, total=5), page(2, total=5, first=2), page(1, total=5, first=4))
    items = harbor.HarborClient(StubModule()).list('/things')
    assert [item['id'] for item in items] == [0, 1, 2, 3, 4]
    assert pages_asked(server, '/things') == [['1'], ['2'], ['3']]


def test_list_stops_at_an_empty_page_whatever_the_total_says(server):
    server.route('GET', '/things', page(2, total=5), page(0, total=5))
    assert len(harbor.HarborClient(StubModule()).list('/things')) == 2
    assert pages_asked(server, '/things') == [['1'], ['2']]


@pytest.mark.parametrize('total', [None, 'many'], ids=['no-header', 'not-a-number'])
def test_list_without_a_usable_total_stops_at_a_short_page(server, total):
    server.route('GET', '/things', page(100, total=total), page(3, total=total, first=100))
    assert len(harbor.HarborClient(StubModule()).list('/things')) == 103
    assert pages_asked(server, '/things') == [['1'], ['2']]


@pytest.mark.parametrize('total', [None, 250], ids=['no-header', 'total-never-reached'])
def test_list_ends_when_a_page_repeats(server, total):
    # An endpoint that ignores `page`: the same page again adds nothing, and must not add duplicates.
    server.route('GET', '/things', page(100, total=total))
    items = harbor.HarborClient(StubModule()).list('/things')
    assert [item['id'] for item in items] == list(range(100))
    assert pages_asked(server, '/things') == [['1'], ['2']]


def test_list_gives_up_after_the_page_limit(server, monkeypatch):
    monkeypatch.setattr(harbor, 'MAX_PAGES', 3)
    server.route('GET', '/things', *[page(100, first=100 * n) for n in range(5)])
    with pytest.raises(ValueError, match='did not end after 3 pages'):
        harbor.HarborClient(StubModule()).list('/things')
    assert pages_asked(server, '/things') == [['1'], ['2'], ['3']]


def test_a_list_that_does_not_end_fails_the_task(server, run_module, monkeypatch):
    monkeypatch.setattr(harbor, 'MAX_PAGES', 2)
    server.route('GET', '/projects', *[page(100, first=100 * n) for n in range(4)])
    result = run_module(project_info.main, {})
    assert result['failed'] is True
    assert 'did not end after 2 pages' in result['msg']
    assert 'exception' not in result


# -- the warning about an untested version -------------------------------------

def untested(server, version='v2.9.0-abc'):
    answer = server.response('systeminfo')
    answer['body']['harbor_version'] = version
    server.route('GET', '/systeminfo', answer)
    server.route('GET', '/projects', 'projects_before')
    server.route('GET', '/quotas', 'quotas_all')


def test_untested_version_warns_and_says_how_to_stop(server, run_module):
    untested(server)
    result = run_module(project_info.main, {})
    assert result.get('failed') is not True
    # A warning is a string up to ansible-core 2.18 and a structure after it.
    assert len(result['warnings']) == 1
    assert 'v2.9.0-abc' in json.dumps(result['warnings'])
    assert 'warn_untested_version' in json.dumps(result['warnings'])


def test_untested_version_warning_can_be_switched_off(server, run_module):
    untested(server)
    result = run_module(project_info.main, dict(warn_untested_version=False))
    assert result.get('failed') is not True
    assert not result.get('warnings')


def test_tested_version_does_not_warn(server, run_module):
    server.route('GET', '/projects', 'projects_before')
    server.route('GET', '/quotas', 'quotas_all')
    result = run_module(project_info.main, {})
    assert not result.get('warnings')


def test_warning_switch_from_the_environment(server, run_module, monkeypatch):
    monkeypatch.setenv('HARBOR_WARN_UNTESTED_VERSION', 'false')
    untested(server)
    assert not run_module(project_info.main, {}).get('warnings')


def test_warning_option_wins_over_the_environment(server, run_module, monkeypatch):
    monkeypatch.setenv('HARBOR_WARN_UNTESTED_VERSION', 'false')
    untested(server)
    result = run_module(project_info.main, dict(warn_untested_version=True))
    assert len(result['warnings']) == 1
