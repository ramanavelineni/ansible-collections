#!/usr/bin/env bash
# Fails when the unit tests cover less of a collection's plugin code than its
# floor. Run from the collection directory after
# `ansible-test units --coverage`; extra arguments go to ansible-test
# (for example --venv --python 3.13).
# Usage: coverage-floor.sh <collection> [ansible-test coverage options]
#
# Floors sit a little under what main measured when they were set (98% for
# both collections, 2026-10-03). Raise them when coverage has risen for good;
# don't lower one to get a change through.
set -euo pipefail

collection="${1:?usage: coverage-floor.sh <collection> [ansible-test options]}"
shift
case "${collection}" in
  semaphoreui) floor=95 ;;
  harbor)      floor=95 ;;
  *) echo "no coverage floor for '${collection}'" >&2; exit 1 ;;
esac

# Only the plugins count: test files cover themselves.
report="$(ansible-test coverage report --include 'plugins/*' --show-missing "$@" </dev/null)"
printf '%s\n' "${report}"
total="$(printf '%s\n' "${report}" | awk '$1 == "TOTAL" { gsub("%", "", $NF); print $NF }')"
case "${total}" in
  ''|*[!0-9]*) echo "could not read the total from the coverage report" >&2; exit 1 ;;
esac
if [ "${total}" -lt "${floor}" ]; then
  echo "plugin coverage of ${collection} is ${total}%, under the floor of ${floor}%" >&2
  exit 1
fi
echo "plugin coverage of ${collection}: ${total}% (floor ${floor}%)"
