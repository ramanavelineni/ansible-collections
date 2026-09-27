# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    HarborError,
    base_url,
    find_by_name,
    id_from_location,
    storage_to_gb,
    version_is_tested,
)


@pytest.mark.parametrize('url, expected', [
    ('https://harbor.example.com', 'https://harbor.example.com'),
    ('https://harbor.example.com/', 'https://harbor.example.com'),
    ('https://harbor.example.com/api/v2.0', 'https://harbor.example.com'),
    ('https://harbor.example.com/api/v2.0/', 'https://harbor.example.com'),
    ('https://harbor.example.com/api', 'https://harbor.example.com'),
    ('https://example.com/harbor/api/v2.0', 'https://example.com/harbor'),
])
def test_base_url(url, expected):
    assert base_url(url) == expected


@pytest.mark.parametrize('version, expected', [
    ('v2.15.2-a97e7b83', True),
    ('v2.14.4-79a297f7', True),
    ('v2.15', True),
    ('v2.13.5-abc', False),
    ('v2.150.1', False),
    ('', False),
    (None, False),
])
def test_version_is_tested(version, expected):
    assert version_is_tested(version) is expected


@pytest.mark.parametrize('headers, expected', [
    ({'location': '/api/v2.0/projects/12'}, 12),
    ({'location': '/api/v2.0/projects/12/'}, 12),
    ({'location': '/api/v2.0/projects/abc'}, None),
    ({}, None),
])
def test_id_from_location(headers, expected):
    assert id_from_location(headers) == expected


@pytest.mark.parametrize('storage, expected', [
    (None, None), (-1, -1), (5 * 1024 ** 3, 5), (1536 * 1024 ** 2, 1.5), (0, 0),
])
def test_storage_to_gb(storage, expected):
    assert storage_to_gb(storage) == expected


def test_find_by_name():
    items = [{'name': 'a'}, {'name': 'b'}]
    assert find_by_name(items, 'b', 'project') == {'name': 'b'}
    assert find_by_name(items, 'z', 'project') is None
    with pytest.raises(ValueError, match='More than one project'):
        find_by_name(items + [{'name': 'a'}], 'a', 'project')


def test_error_messages():
    assert 'HTTP 409: (empty body)' in HarborError('POST', 'u', status=409, response='').message()
    assert 'without an HTTP response: reset' in HarborError('GET', 'u', reason='reset').message()
