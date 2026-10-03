# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Answers the modules don't expect end as a failed task with a message, not as a Python traceback."""

import json
from http.client import BadStatusLine, IncompleteRead

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    info,
    registry,
    replication,
    robot_account,
    tag_immutability,
)

PULL_ALL = [dict(namespace='*', access=[dict(resource='repository', action='pull')])]
# Quote and backslash: Ansible's own masking doesn't find such a value once it is JSON-encoded.
SECRET = 'quoted"Zebra7\\pw'


def clean_failure(result, name):
    assert result['failed'] is True
    assert result['msg'].startswith('Unexpected %s: ' % name)
    # The traceback goes into `exception`, which ansible-core keeps or drops
    # depending on its version and verbosity. It is never part of the message.
    assert 'Traceback' not in result['msg']


def test_create_answered_with_an_empty_body(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_empty')
    server.route('POST', '/robots', dict(status=201, body=None, headers={}))
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', permissions=PULL_ALL, secret=SECRET))
    clean_failure(result, 'TypeError')
    assert 'Zebra7' not in json.dumps(result)


def test_create_answered_without_a_location(server, run_module):
    project_id = int(server.fixtures['tag_project_create']['headers']['location'].rsplit('/', 1)[-1])
    rules = '/projects/%d/immutabletagrules' % project_id
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % project_id, 'tag_project_get')
    server.route('GET', rules, 'tag_immutability_list_empty')
    server.route('POST', rules, dict(status=201, body=None, headers={}))
    result = run_module(tag_immutability.main, dict(project='fixtures-tag-policy', tags='v*', disabled=True))
    clean_failure(result, 'TypeError')
    assert server.calls('PUT') == []


def test_rule_names_a_registry_the_listing_does_not_have(server, run_module):
    server.route('GET', '/replication/policies', 'registry_replication_list')
    server.route('GET', '/registries', dict(status=200, body=[], headers={}))
    result = run_module(replication.main, dict(name='rr-fixtures-pull', speed=256))
    clean_failure(result, 'KeyError')
    assert 'rr-fixtures-self' in result['msg']
    assert server.calls('PUT') == []


@pytest.mark.parametrize('error', [BadStatusLine('SSH-2.0-OpenSSH_9.6'), IncompleteRead(b'{"harbor_ver')],
                         ids=['not-http', 'cut-short'])
def test_broken_http_answer_is_a_connection_failure(server, run_module, error):
    server.route('GET', '/systeminfo', error)
    result = run_module(info.main, dict(retries=2))
    assert result['failed'] is True
    assert 'without an HTTP response' in result['msg']
    assert 'exception' not in result
    assert result['request_details']['method'] == 'GET'
    # Retried like any other connection failure.
    assert len(server.calls('GET', '/systeminfo')) == 3


def test_broken_http_answer_to_a_write_shows_no_secret(server, run_module):
    server.route('GET', '/registries', 'registry_list_before')
    server.route('POST', '/registries', BadStatusLine(''))
    result = run_module(registry.main, dict(name='rr-fixtures-self', type='harbor', endpoint_url='http://proxy:8080/',
                                            access_key='admin', access_secret=SECRET))
    assert result['failed'] is True
    assert 'without an HTTP response' in result['msg']
    assert result['request_details']['request']['credential']['access_secret'] == '********'
    assert 'Zebra7' not in json.dumps(result)
    # A create is not sent twice.
    assert len(server.calls('POST', '/registries')) == 1


def test_a_usage_error_keeps_its_own_message(server, run_module):
    server.route('GET', '/replication/policies', 'registry_replication_list_before')
    server.route('GET', '/registries', 'registry_list')
    result = run_module(replication.main, dict(name='rr-fixtures-new'))
    assert result['failed'] is True
    assert 'src_registry' in result['msg'] and not result['msg'].startswith('Unexpected')
    assert 'exception' not in result
