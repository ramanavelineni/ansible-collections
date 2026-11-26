#!/usr/bin/env python3
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Prints the matrix of a collection's role-test jobs, as JSON for `include:`.

    .github/scripts/role-test-matrix.py <collection> <event>   (from the repository root)

The server versions, each with the ansible-core it runs with, are in
.github/role-tests.json, oldest first. The playbooks are every *.yml directly
in the collection's tests/roles/, as `make role-test` runs them. A pull request
(<event> pull_request) runs only the newest version; anything else runs every
version. Each entry is one job: the version's keys plus "playbook".

The versions live outside .github/workflows/ so that a server release is
tested without changing a workflow file, which pushing needs a token with the
workflow scope for.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
VERSIONS = os.path.join(ROOT, '.github', 'role-tests.json')


def playbooks(collection, root=ROOT):
    directory = os.path.join(root, 'ansible_collections', 'ramanavelineni', collection, 'tests', 'roles')
    return sorted(name[:-len('.yml')] for name in os.listdir(directory)
                  if name.endswith('.yml') and os.path.isfile(os.path.join(directory, name)))


def matrix(collection, event, config=None, root=ROOT):
    if config is None:
        with open(VERSIONS) as f:
            config = json.load(f)
    if collection not in config:
        raise ValueError('%s has no role tests in %s (known: %s)' % (collection, VERSIONS, ', '.join(sorted(config))))
    versions = config[collection]['versions']
    if not versions:
        raise ValueError('%s lists no versions in %s' % (collection, VERSIONS))
    if event == 'pull_request':
        versions = versions[-1:]
    return [dict(version, playbook=playbook) for version in versions for playbook in playbooks(collection, root)]


def main(argv):
    if len(argv) != 3:
        sys.exit('usage: role-test-matrix.py <collection> <event>')
    try:
        print(json.dumps(matrix(argv[1], argv[2])))
    except ValueError as e:
        sys.exit('role-test-matrix.py: %s' % e)


if __name__ == '__main__':
    main(sys.argv)
