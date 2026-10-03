#!/usr/bin/env bash
# Reads changed file names on stdin and prints, as GITHUB_OUTPUT lines, what
# CI has to run:
#   collections=["harbor"]   collections whose ansible-test jobs run
#   tools=true|false         whether the tests in tools/tests run
# First argument:
#   (none)          decide from the file names
#   all             the changed files are unknown: run everything
#   only "<names>"  run exactly these collections, whatever changed (the release
#                   workflow tests the tagged collection this way); stdin is not
#                   read, and a name that is not a collection is an error
set -euo pipefail

ALL='semaphoreui harbor'

if [ "${1:-}" = only ]; then
  json=''
  for name in ${2:-}; do
    case " ${ALL} " in
      *" ${name} "*) json="${json:+${json},}\"${name}\"" ;;
      *) echo "ci-changes.sh: '${name}' is not a collection (${ALL})" >&2; exit 1 ;;
    esac
  done
  if [ -z "${json}" ]; then
    echo "ci-changes.sh: 'only' needs a collection name (${ALL})" >&2
    exit 1
  fi
  echo "collections=[${json}]"
  echo "tools=false"
  exit 0
fi

# A change here can break any job.
SHARED='^(\.github/workflows/ci\.yml|\.github/scripts/|Makefile$)'

# Markdown has nothing for ansible-test to check. Module docs live in .py files.
files="$(grep -v '\.md$' || true)"

collections=''
tools=false
if [ "${1:-}" = all ] || grep -qE "${SHARED}" <<<"${files}"; then
  collections="${ALL}"
  tools=true
else
  for name in ${ALL}; do
    if grep -q "^ansible_collections/ramanavelineni/${name}/" <<<"${files}"; then
      collections="${collections} ${name}"
    fi
  done
  if grep -q '^tools/' <<<"${files}"; then
    tools=true
  fi
fi

json=''
for name in ${collections}; do
  json="${json:+${json},}\"${name}\""
done
echo "collections=[${json}]"
echo "tools=${tools}"
