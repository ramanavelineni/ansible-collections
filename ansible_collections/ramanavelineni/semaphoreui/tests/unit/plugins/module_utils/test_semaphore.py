# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    SemaphoreError,
    base_url,
    diff_fields,
    find_by_name,
    version_is_tested,
)


@pytest.mark.parametrize('url, expected', [
    ('https://semaphore.example.com', 'https://semaphore.example.com'),
    ('https://semaphore.example.com/', 'https://semaphore.example.com'),
    ('https://semaphore.example.com/api', 'https://semaphore.example.com'),
    ('https://semaphore.example.com/api/', 'https://semaphore.example.com'),
    ('https://example.com/semaphore/api', 'https://example.com/semaphore'),
    ('https://example.com/apis', 'https://example.com/apis'),
])
def test_base_url(url, expected):
    assert base_url(url) == expected


@pytest.mark.parametrize('version, expected', [
    ('v2.19.12', True),
    ('2.18.30', True),
    ('v2.19', True),
    ('v2.17.3', False),
    ('v2.20.0', False),
    ('v2.180.1', False),
    ('', False),
    (None, False),
    ('develop', False),
])
def test_version_is_tested(version, expected):
    assert version_is_tested(version) is expected


def test_find_by_name_single_match():
    items = [{'id': 1, 'name': 'a'}, {'id': 2, 'name': 'b'}]
    assert find_by_name(items, 'b', 'project') == {'id': 2, 'name': 'b'}


def test_find_by_name_no_match():
    assert find_by_name([{'id': 1, 'name': 'a'}], 'z', 'project') is None


def test_find_by_name_duplicate_names_fail():
    items = [{'id': 1, 'name': 'a'}, {'id': 7, 'name': 'a'}]
    with pytest.raises(ValueError, match=r"More than one project is named 'a' \(ids 1, 7\)"):
        find_by_name(items, 'a', 'project')


def test_find_by_name_other_field():
    assert find_by_name([{'id': 3, 'title': 'All'}], 'All', 'view', field='title')['id'] == 3


def test_diff_fields_ignores_unmanaged_and_equal():
    desired = {'alert': True, 'alert_chat': None, 'max_parallel_tasks': 0}
    current = {'alert': False, 'alert_chat': 'x', 'max_parallel_tasks': 0}
    assert diff_fields(desired, current) == ['alert']


def test_semaphore_error_messages():
    empty = SemaphoreError('PUT', 'https://s/api/project/1', status=400, response='')
    assert 'HTTP 400: (empty body)' in empty.message()
    transport = SemaphoreError('GET', 'https://s/api/info', reason='connection reset')
    assert 'failed without an HTTP response: connection reset' in transport.message()
    assert transport.details()['status'] is None
