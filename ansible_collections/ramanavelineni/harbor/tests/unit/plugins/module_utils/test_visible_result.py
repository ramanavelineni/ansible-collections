# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The harness shows a result as a user sees it, and hides no more than the controller would."""

import pytest

from ansible_collections.ramanavelineni.harbor.tests.unit.plugins.utils import MASK, visible_result


def seen(value, *secrets):
    return visible_result(dict(_ansible_new_secrets=list(secrets), value=value))['value']


def test_a_result_without_reported_secrets_is_left_alone():
    raw = dict(changed=True, msg='s3cret-pw')
    assert visible_result(raw) is raw


def test_the_key_is_removed_also_when_it_is_empty():
    assert visible_result(dict(_ansible_new_secrets=[], msg='x')) == dict(msg='x')


def test_a_long_secret_is_masked_wherever_it_occurs():
    assert seen('xs3cret-pwx and s3cret-pw', 's3cret-pw') == 'x%sx and %s' % (MASK, MASK)


def test_a_secret_is_masked_in_keys_lists_and_nested_values():
    result = visible_result({'_ansible_new_secrets': ['s3cret-pw'], 's3cret-pw': [dict(a='s3cret-pw')]})
    assert result == {MASK: [dict(a=MASK)]}


def test_a_secret_is_masked_as_it_is_written_inside_json():
    secret = 'quoted"Zebra7\\pw'
    assert seen('{"password": "quoted\\"Zebra7\\\\pw"}', secret) == '{"password": "%s"}' % MASK
    assert seen(secret, secret) == MASK


@pytest.mark.parametrize('text, expected', [
    ('abcd', MASK),
    ('(abcd)', '(%s)' % MASK),
    ('xabcd', 'xabcd'),
    ('abcd1', 'abcd1'),
])
def test_a_short_secret_is_masked_only_where_it_stands_alone(text, expected):
    assert seen(text, 'abcd') == expected


def test_a_value_too_short_to_be_a_secret_is_not_masked():
    assert seen('abc', 'abc') == 'abc'


def test_whitespace_around_a_secret_is_not_part_of_it():
    assert seen('tok12345', ' tok12345\n') == MASK


def test_secrets_that_overlap_or_touch_become_one_mask():
    assert seen('s3cret-pws3cret-pw', 's3cret-pw') == MASK
    assert seen('abcdefgh', 'abcdefg', 'defghij', 'bcdefgh') == MASK


def test_a_number_that_is_a_secret_is_masked_and_others_are_kept():
    assert seen(12345678, '12345678') == MASK
    assert seen(123, '12345678') == 123
    assert seen(True, 'True') is True


def test_a_secret_the_module_did_not_report_stays_visible():
    assert seen('other-secret', 's3cret-pw') == 'other-secret'
