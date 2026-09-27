# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import info


def test_info(server, run_module):
    result = run_module(info.main, {})
    assert result['changed'] is False
    assert result['version'] == server.fixtures['info']['body']['version']
    assert result['version'].lstrip('v').startswith(server.version + '.')
    assert result['tested'] is True
    assert 'ansible' in [app['id'] for app in result['apps']]
    assert result['info']['version'] == result['version']


def test_info_untested_version(server, run_module):
    body = server.response('info')
    body['body']['version'] = 'v2.99.0'
    server.route('GET', '/info', body)
    result = run_module(info.main, {})
    assert result['tested'] is False
    # info reports the version through `tested` instead of warning about it.
    assert 'v2.99.0' not in json.dumps(result.get('warnings', []))
