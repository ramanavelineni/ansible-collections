#!/usr/bin/env bash
# Reads changed file names on stdin and prints, as GITHUB_OUTPUT lines, what
# CI has to run:
#   collections=["harbor"]   collections whose ansible-test jobs run
#   tools=true|false         whether the tests in tools/tests run
# "all" as the first argument means the changed files are unknown: run everything.
set -euo pipefail

ALL='semaphoreui harbor'
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
