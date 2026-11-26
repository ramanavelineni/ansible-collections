#!/usr/bin/env python3
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Prints, as GITHUB_OUTPUT lines, the ansible-core versions the CI jobs run.

    .github/scripts/ci-versions.py <event>   (from the repository root)

The supported ansible-core versions are in .github/ci-versions.json, oldest
first, each with the oldest and the newest Python it supports for modules
(REMOTE_ONLY_PYTHON_VERSIONS and CONTROLLER_PYTHON_VERSIONS in ansible-core's
test/lib/ansible_test/_util/target/common/constants.py). From them:

    ansible_all=["2.20", "2.21", "2.22"]     sanity: every version
    ansible_units=["2.20", "2.21"]           units without coverage: all but the newest
    ansible_units_python=[{"ansible": ..., "oldest": ..., "newest": ...}, ...]
                                             their Pythons (a pull request runs these two)
    ansible_newest=2.22                      units with coverage, and the lint job
    ansible_install=["2.20", "2.22"]         install test: oldest and newest;
                                             a pull request ("pull_request") the oldest only

The versions live outside .github/workflows/ so that a new ansible-core
version is a change to that file, which pushing needs no token with the
workflow scope for.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(HERE), 'ci-versions.json')
MINOR = re.compile(r'^\d+\.\d+$')


def load(path=CONFIG):
    with open(path) as f:
        return json.load(f)['ansible']


def check(entries):
    """Fail on what the jobs could not use."""
    if not entries:
        raise ValueError('no ansible-core version')
    versions = [e.get('version', '') for e in entries]
    for entry in entries:
        for key in ('version', 'python_oldest', 'python_newest'):
            if not MINOR.match(entry.get(key) or ''):
                raise ValueError('%s of %r is not a major.minor version' % (key, entry))
    keyed = [tuple(int(p) for p in v.split('.')) for v in versions]
    if keyed != sorted(keyed) or len(set(keyed)) != len(keyed):
        raise ValueError('the versions are not oldest first, each once: %s' % ', '.join(versions))


def outputs(entries, event):
    check(entries)
    versions = [e['version'] for e in entries]
    older = entries[:-1]
    return dict(
        ansible_all=versions,
        ansible_units=[e['version'] for e in older],
        ansible_units_python=[dict(ansible=e['version'], oldest=e['python_oldest'], newest=e['python_newest'])
                              for e in older],
        ansible_newest=versions[-1],
        ansible_install=versions[:1] if event == 'pull_request' else sorted(set([versions[0], versions[-1]]),
                                                                            key=versions.index),
    )


def main(argv):
    if len(argv) != 2:
        sys.exit('usage: ci-versions.py <event>')
    try:
        found = outputs(load(), argv[1])
    except (ValueError, KeyError) as e:
        sys.exit('ci-versions.py: %s: %s' % (CONFIG, e))
    for key, value in found.items():
        print('%s=%s' % (key, value if isinstance(value, str) else json.dumps(value)))


if __name__ == '__main__':
    main(sys.argv)
