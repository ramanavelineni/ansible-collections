#!/usr/bin/env bash
# Runs ansible-test with the given arguments. When it fails while starting its
# test container, it runs again, up to five attempts in all with a pause
# between them; any other failure ends it at once with ansible-test's exit
# status.
#
# ansible-test 2.22.0 sometimes fails to start the default test container
# (v2.22-8) on GitHub's runners: the privileged helper that remounts the
# container's cgroup filesystem and then wakes it with `pkill sleep` finds no
# `sleep` yet, and exits with 1 before any test runs. Its line in the output:
#   Command "docker run ... --name ansible-test-init-controller-... sh -c 'mount -o remount,rw /sys/fs/cgroup/ && pkill sleep'" returned exit status 1.
# shortcut: retries instead of a fix in ansible-test; drop this script (and its
# use in ci.yml) once a 2.22 release no longer fails this way.
#
# Usage: ansible-test-retry.sh <ansible-test arguments>   (from a collection directory)
set -uo pipefail

attempts=5
# Seconds between two attempts; three attempts in a row once failed without it.
pause=10
log="$(mktemp)"
trap 'rm -f "${log}"' EXIT

for attempt in $(seq 1 "${attempts}"); do
  ansible-test "$@" 2>&1 | tee "${log}"
  status="${PIPESTATUS[0]}"
  if [ "${status}" -eq 0 ]; then
    exit 0
  fi
  # --color yes wraps lines in escape sequences; take them out before matching.
  if ! sed -E 's/\x1b\[[0-9;]*m//g' "${log}" \
      | grep -Eq "Command \"docker run .*--name ansible-test-init-.*pkill sleep'\" returned exit status 1"; then
    exit "${status}"
  fi
  if [ "${attempt}" -lt "${attempts}" ]; then
    echo "::warning::ansible-test could not start its test container (attempt ${attempt} of ${attempts}); running it again in ${pause} seconds."
    sleep "${pause}"
  fi
done
echo "::error::ansible-test could not start its test container in ${attempts} attempts."
exit "${status}"
