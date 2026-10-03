# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.replication import normalize_filter, validate_cron
from ansible_collections.ramanavelineni.harbor.plugins.modules import replication, replication_info

PULL = dict(name='rr-fixtures-pull', src_registry='rr-fixtures-self', dest_namespace='library', enabled=False,
            override=True, trigger=dict(type='manual'),
            filters=[dict(type='name', value='library/**'), dict(type='tag', value='v*', decoration='excludes')])


def rule_id(server):
    return int(server.fixtures['registry_replication_create']['headers']['location'].rsplit('/', 1)[-1])


def reg_id(server):
    return int(server.fixtures['registry_create']['headers']['location'].rsplit('/', 1)[-1])


def routes(server, rules='registry_replication_list'):
    server.route('GET', '/replication/policies', rules)
    server.route('GET', '/registries', 'registry_list')


def stored(server, fixture='registry_replication_get_updated', **fields):
    """A recorded single-rule answer, for the read after an update.

    With `fields`, hand-edited: those fields are written into the recorded body,
    because no update with that outcome was recorded.
    """
    answer = server.response(fixture)
    answer['body'].update(fields)
    return answer


def updating(server, answer='registry_replication_get_updated'):
    server.route('PUT', '/replication/policies/%d' % rule_id(server), 'registry_replication_update')
    server.route('GET', '/replication/policies/%d' % rule_id(server), answer)


def test_create(server, run_module):
    routes(server, 'registry_replication_list_before')
    server.route('POST', '/replication/policies', 'registry_replication_create')
    server.route('GET', '/replication/policies/%d' % rule_id(server), 'registry_replication_get')
    result = run_module(replication.main, PULL)
    assert result['changed'] is True
    assert result['replication']['src_registry'] == 'rr-fixtures-self'
    assert result['replication']['dest_registry'] is None
    body = server.calls('POST', '/replication/policies')[0]['body']
    assert body['src_registry'] == dict(id=reg_id(server))
    assert 'dest_registry' not in body
    assert body['trigger'] == dict(type='manual')
    assert body['dest_namespace_replace_count'] == -1
    assert body['filters'] == [dict(type='name', value='library/**'), dict(type='tag', value='v*', decoration='excludes')]


def test_create_check_mode(server, run_module):
    routes(server, 'registry_replication_list_before')
    result = run_module(replication.main, PULL, check_mode=True)
    assert result['changed'] is True
    assert server.calls('POST') == []


def test_create_needs_registry(server, run_module):
    routes(server, 'registry_replication_list_before')
    result = run_module(replication.main, dict(name='rr-fixtures-new'))
    assert result['failed'] is True
    assert 'src_registry' in result['msg']


def test_unknown_registry(server, run_module):
    routes(server, 'registry_replication_list_before')
    result = run_module(replication.main, dict(PULL, src_registry='nope'))
    assert result['failed'] is True
    assert "'nope' does not exist" in result['msg']


def test_no_change_filters_in_any_order(server, run_module):
    routes(server)
    result = run_module(replication.main, dict(PULL, filters=list(reversed(PULL['filters']))))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def stored_tag_decoration(server, decoration):
    """The recorded rule list with its tag filter's decoration replaced (None: left out).

    Hand-made: every recorded tag filter excludes. The audit reports that the
    UI stores a matching one as `matches`.
    """
    listing = server.response('registry_replication_list')
    for item in listing['body'][0]['filters']:
        if item['type'] == 'tag':
            item.pop('decoration', None)
            if decoration:
                item['decoration'] = decoration
    return listing


@pytest.mark.parametrize('stored', ['matches', None])
@pytest.mark.parametrize('declared', ['matches', None])
def test_no_decoration_and_matches_are_the_same_filter(server, run_module, stored, declared):
    routes(server, stored_tag_decoration(server, stored))
    tag = dict(type='tag', value='v*')
    if declared:
        tag['decoration'] = declared
    result = run_module(replication.main, dict(PULL, filters=[dict(type='name', value='library/**'), tag]))
    assert result['changed'] is False
    assert server.calls('PUT') == []
    assert result['replication']['filters'] == [dict(type='name', value='library/**', decoration=''),
                                                dict(type='tag', value='v*', decoration='matches')]


def test_excludes_still_differs_from_no_decoration(server, run_module):
    routes(server, stored_tag_decoration(server, None))
    updating(server, 'registry_replication_get')
    result = run_module(replication.main, PULL)
    assert result['changed'] is True
    assert dict(type='tag', value='v*', decoration='excludes') in server.calls('PUT')[0]['body']['filters']


def test_filter_without_decoration_is_sent_as_matches(server, run_module):
    routes(server, 'registry_replication_list_before')
    server.route('POST', '/replication/policies', 'registry_replication_create')
    server.route('GET', '/replication/policies/%d' % rule_id(server), 'registry_replication_get')
    run_module(replication.main, dict(PULL, filters=[dict(type='name', value='library/**'), dict(type='tag', value='v*'),
                                                     dict(type='label', value=['stable'])]))
    assert server.calls('POST', '/replication/policies')[0]['body']['filters'] == [
        dict(type='name', value='library/**'), dict(type='tag', value='v*', decoration='matches'),
        dict(type='label', value=['stable'], decoration='matches')]


def test_update_sends_whole_rule(server, run_module):
    routes(server)
    updating(server)
    result = run_module(replication.main, dict(name='rr-fixtures-pull', speed=256))
    assert result['changed'] is True
    assert result['replication']['speed'] == 256
    assert not result.get('warnings')
    body = server.calls('PUT')[0]['body']
    assert body['speed'] == 256
    assert body['src_registry'] == dict(id=reg_id(server))
    assert body['dest_namespace'] == 'library'
    assert len(body['filters']) == 2
    assert body['override'] is True and body['enabled'] is False


def test_scheduled_trigger(server, run_module):
    routes(server)
    updating(server)
    result = run_module(replication.main, dict(name='rr-fixtures-pull', trigger=dict(type='scheduled', cron='0 0 3 * * *')))
    assert result['changed'] is True
    assert result['replication']['trigger'] == dict(type='scheduled', cron='0 0 3 * * *')
    assert not result.get('warnings')
    assert server.calls('PUT')[0]['body']['trigger'] == dict(type='scheduled', trigger_settings=dict(cron='0 0 3 * * *'))


def test_no_change_after_update(server, run_module):
    routes(server, 'registry_replication_list_updated')
    result = run_module(replication.main, dict(name='rr-fixtures-pull', speed=256,
                                               trigger=dict(type='scheduled', cron='0 0 3 * * *')))
    assert result['changed'] is False


def test_bad_cron_refused_before_sending(server, run_module):
    routes(server)
    result = run_module(replication.main, dict(name='rr-fixtures-pull', trigger=dict(type='scheduled', cron='0 * * * * *')))
    assert result['failed'] is True
    assert 'minutes' in result['msg']
    assert server.calls('PUT') == []


def test_event_based_with_single_active_refused(server, run_module):
    routes(server)
    result = run_module(replication.main, dict(name='rr-fixtures-pull', trigger=dict(type='event_based'),
                                               single_active_replication=True))
    assert result['failed'] is True
    assert 'single_active_replication' in result['msg']


def test_switch_direction(server, run_module):
    routes(server)
    # Hand-edited answer: the recorded rule with its two registries swapped.
    rule = server.fixtures['registry_replication_get']['body']
    updating(server, stored(server, 'registry_replication_get', src_registry=rule['dest_registry'],
                            dest_registry=rule['src_registry']))
    result = run_module(replication.main, dict(name='rr-fixtures-pull', dest_registry='rr-fixtures-self'))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    assert body['dest_registry'] == dict(id=reg_id(server)) and 'src_registry' not in body


def test_delete(server, run_module):
    routes(server)
    server.route('DELETE', '/replication/policies/%d' % rule_id(server), 'registry_replication_delete')
    result = run_module(replication.main, dict(name='rr-fixtures-pull', state='absent'))
    assert result['changed'] is True


def test_delete_missing(server, run_module):
    routes(server, 'registry_replication_list_before')
    result = run_module(replication.main, dict(name='rr-fixtures-pull', state='absent'))
    assert result['changed'] is False


def test_replication_info(server, run_module):
    server.route('GET', '/replication/policies', 'registry_replication_list_updated')
    result = run_module(replication_info.main, dict(name='rr-fixtures-pull'))
    rule = result['replications'][0]
    assert rule['trigger'] == dict(type='scheduled', cron='0 0 3 * * *')
    assert rule['speed'] == 256 and rule['dest_registry'] is None


@pytest.mark.parametrize('cron, ok', [
    ('0 0 2 * * *', True), ('0 30 */6 * * 1-5', True),
    ('0 * * * * *', False), ('5 0 2 * * *', False), ('0 2 * * *', False), ('', False),
])
def test_validate_cron(cron, ok):
    if ok:
        validate_cron(cron)
    else:
        with pytest.raises(ValueError):
            validate_cron(cron)


@pytest.mark.parametrize('item, error', [
    (dict(type='name', value='a/**'), None),
    (dict(type='label', value='one'), None),
    (dict(type='tag', value='v*'), None),
    (dict(type='tag', value='v*', decoration=''), None),
    (dict(type='label', value=['b', 'a'], decoration='excludes'), None),
    (dict(type='resource', value='artifact'), None),
    (dict(type='resource', value='chart'), 'resource filter value'),
    (dict(type='name', value='x', decoration='matches'), 'decoration'),
    (dict(type='tag', value=['x']), 'string'),
    (dict(type='label', value=[1]), 'list of label names'),
])
def test_normalize_filter(item, error):
    if error is None:
        normalized = normalize_filter(item)
        assert normalized['type'] == item['type']
        default = 'matches' if item['type'] in ('tag', 'label') else ''
        assert normalized['decoration'] == (item.get('decoration') or default)
    else:
        with pytest.raises(ValueError, match=error):
            normalize_filter(item)


# -- the result of an update is read back --------------------------------------

def test_update_result_is_what_harbor_stored(server, run_module):
    # Hand-edited answer: the recorded rule after the update, with a speed Harbor
    # would have had to change on store. No such update was recorded.
    routes(server)
    updating(server, stored(server, speed=128))
    result = run_module(replication.main, dict(name='rr-fixtures-pull', speed=256))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['speed'] == 256
    assert result['replication']['speed'] == 128
    assert result['diff']['after'] == result['replication']
    assert len(result['warnings']) == 1
    assert 'speed' in str(result['warnings'])
    # One request more than before: the read after the write.
    path = '/replication/policies/%d' % rule_id(server)
    assert [(r['method'], r['path']) for r in server.requests[-2:]] == [('PUT', path), ('GET', path)]


def test_update_check_mode_predicts_the_real_result(server, run_module):
    # The recorded rule after the update also carries the scheduled trigger of
    # a later recorded step, so both are declared here.
    routes(server)
    updating(server)
    args = dict(name='rr-fixtures-pull', speed=256, trigger=dict(type='scheduled', cron='0 0 3 * * *'))
    real = run_module(replication.main, args)
    check = run_module(replication.main, args, check_mode=True)
    assert not real.get('warnings')
    assert check['replication'] == real['replication']
    assert check['diff'] == real['diff']
