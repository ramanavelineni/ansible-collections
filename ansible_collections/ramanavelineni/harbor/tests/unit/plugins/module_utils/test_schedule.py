# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.schedule import (
    carried_parameters,
    desired_timing,
    parse_parameters,
    require_known_type,
    schedule_body,
    split_types,
)

CURRENT = dict(schedule='custom', cron='0 0 4 * * 0', next_scheduled_time=None)


@pytest.mark.parametrize('params, current, expected', [
    (dict(), None, ('none', '')),
    (dict(), CURRENT, ('custom', '0 0 4 * * 0')),
    (dict(schedule='daily'), None, ('daily', '0 0 0 * * *')),
    (dict(schedule='hourly', cron='0 0 * * * *'), None, ('hourly', '0 0 * * * *')),
    (dict(cron='0 30 2 * * *'), CURRENT, ('custom', '0 30 2 * * *')),
    (dict(schedule='none'), CURRENT, ('none', '')),
])
def test_desired_timing(params, current, expected):
    assert desired_timing(params, current) == expected


@pytest.mark.parametrize('params, message', [
    (dict(schedule='custom'), 'needs cron'),
    (dict(schedule='custom', cron='0 4 * * 0'), 'Harbor uses 6'),
    (dict(schedule='weekly', cron='0 0 1 * * 0'), 'use schedule: custom'),
    (dict(schedule='none', cron='0 0 1 * * *'), 'cron can only be set'),
])
def test_desired_timing_invalid(params, message):
    with pytest.raises(ValueError, match=message):
        desired_timing(params, CURRENT)


def test_parse_parameters_strips_internal_attributes():
    raw = '{"workers": 2, "redis_url_reg": "redis://:pw@redis:6379/1", "time_window": 2}'
    assert parse_parameters(raw) == dict(workers=2)
    assert parse_parameters(dict(workers=1, redis_url_reg='x')) == dict(workers=1)
    assert parse_parameters('') == {}
    assert parse_parameters('not json') == {}
    assert parse_parameters(None) == {}


def test_schedule_body():
    assert schedule_body('none', '') == dict(schedule=dict(type='None'))
    assert schedule_body('custom', '0 0 4 * * 0', dict(workers=2)) == dict(
        schedule=dict(type='Custom', cron='0 0 4 * * 0'), parameters=dict(workers=2))


def test_schedule_body_refuses_an_unknown_type():
    with pytest.raises(ValueError, match="type 'manual'"):
        schedule_body('manual', '0 0 4 * * 0', dict(workers=2))


def test_require_known_type():
    for kind in ('none', 'hourly', 'daily', 'weekly', 'custom'):
        require_known_type(kind)
    with pytest.raises(ValueError, match='Set schedule'):
        require_known_type('manual')


def test_carried_parameters_keeps_everything_with_a_value():
    stored = parse_parameters('{"workers": 2, "dry_run": true, "delete_tag": null, "redis_url_reg": "redis://x"}')
    assert carried_parameters(stored) == dict(workers=2, dry_run=True)


@pytest.mark.parametrize('stored, expected', [
    ('delete_artifact,create_artifact', ['create_artifact', 'delete_artifact']),
    ('create_artifact,,create_artifact', ['create_artifact']),
    (['b', 'a', 'b'], ['a', 'b']),
    ('', []),
    (None, []),
])
def test_split_types(stored, expected):
    assert split_types(stored) == expected
