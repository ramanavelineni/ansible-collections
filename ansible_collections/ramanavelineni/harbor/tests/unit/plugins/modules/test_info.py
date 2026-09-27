# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

from ansible_collections.ramanavelineni.harbor.plugins.modules import info


def test_info(server, run_module):
    result = run_module(info.main, {})
    assert result['changed'] is False
    assert result['version'] == server.fixtures['systeminfo']['body']['harbor_version']
    assert result['version'].lstrip('v').startswith(server.version + '.')
    assert result['tested'] is True
    assert server.requests[0]['headers']['Authorization'].startswith('Basic ')


def test_bad_credentials_fail(server, run_module):
    server.route('GET', '/systeminfo', 'systeminfo_anonymous')
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert 'did not accept the credentials' in result['msg']
    assert 's3cret-pw' not in json.dumps(result)


def test_api_url_accepted(server, run_module):
    result = run_module(info.main, dict(url='https://harbor.example.com/api/v2.0/'))
    assert result['tested'] is True
    assert server.requests[0]['path'] == '/systeminfo'
