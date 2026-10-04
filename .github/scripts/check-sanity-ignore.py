#!/usr/bin/env python3
"""Checks a collection's tests/sanity/ignore-<version>.txt files.

Every module needs one entry in each file: the collection is Apache-2.0, and
validate-modules expects the GPL header. Nothing else may sit in these files
without saying why, because an ignore entry switches a check off for good.

Checked, for the collection given as the only argument:
  - there is one file for each ansible-core version the sanity job of CI goes
    through (.github/workflows/ci.yml), and no file for another version
  - each file has exactly one licence entry for every module, and none for a
    file that doesn't exist
  - every line carries a comment that explains it
  - lines are unique and sorted, so two files can be compared at a glance

Usage: check-sanity-ignore.py <collection>     (from the repository root)
"""

import os
import re
import sys

LICENCE = 'validate-modules:missing-gplv3-license'


def matrix_versions(workflow):
    """ansible-core versions the sanity job goes through, as '2.18', '2.19', ..."""
    with open(workflow) as f:
        text = f.read()
    # The job, up to the next one: jobs sit at two spaces of indentation.
    job = re.split(r'\n  [a-z][a-z-]*:\n', text.split('\n  sanity:\n', 1)[1], maxsplit=1)[0]
    line = re.search(r'^\s+for version in ([0-9. ]+); do\s*$', job, re.M)
    if not line:
        raise SystemExit('cannot find the versions the sanity job goes through in %s '
                         '(a line "for version in 2.18 2.19 ...; do")' % workflow)
    return line.group(1).split()


def check(collection_dir, versions):
    errors = []
    modules = sorted(name for name in os.listdir(os.path.join(collection_dir, 'plugins', 'modules'))
                     if name.endswith('.py') and name != '__init__.py')
    sanity = os.path.join(collection_dir, 'tests', 'sanity')
    found = sorted(name for name in os.listdir(sanity) if name.startswith('ignore-'))
    wanted = sorted('ignore-%s.txt' % v for v in versions)
    for name in wanted:
        if name not in found:
            errors.append('%s is missing: the sanity job of CI runs ansible-core %s' % (name, name[7:-4]))
    for name in found:
        if name not in wanted:
            errors.append('%s is for a version that the sanity job of CI does not run' % name)

    for name in found:
        path = os.path.join(sanity, name)
        with open(path) as f:
            lines = [line.rstrip('\n') for line in f]
        licensed = []
        for number, line in enumerate(lines, 1):
            where = '%s:%d' % (name, number)
            if not line.strip():
                errors.append('%s: empty line' % where)
                continue
            entry, sep, comment = line.partition(' # ')
            if not sep or not comment.strip():
                errors.append('%s: no comment that explains the entry' % where)
            parts = entry.split()
            if len(parts) != 2:
                errors.append('%s: expected "<path> <test>[:<code>] # <reason>"' % where)
                continue
            target, test = parts
            if not os.path.exists(os.path.join(collection_dir, target)):
                errors.append('%s: %s does not exist' % (where, target))
            if test == LICENCE:
                licensed.append(target)
        if lines != sorted(set(lines)):
            errors.append('%s: lines are not unique and sorted' % name)
        for module in modules:
            count = licensed.count('plugins/modules/' + module)
            if count != 1:
                errors.append('%s: %d licence entries for plugins/modules/%s, expected 1' % (name, count, module))
    return errors, len(modules), found


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.strip().splitlines()[-1].strip())
    collection = sys.argv[1]
    collection_dir = os.path.join('ansible_collections', 'ramanavelineni', collection)
    if not os.path.isdir(collection_dir):
        raise SystemExit('no collection at %s' % collection_dir)
    versions = matrix_versions(os.path.join('.github', 'workflows', 'ci.yml'))
    errors, modules, found = check(collection_dir, versions)
    for error in errors:
        print('%s: %s' % (collection, error), file=sys.stderr)
    if errors:
        raise SystemExit(1)
    print('%s: %d modules, %s all in order' % (collection, modules, ', '.join(found)))


if __name__ == '__main__':
    main()
