#!/usr/bin/env bash
# Runs a collection's role tests: every playbook in its tests/roles/ directory,
# one after the other, against the server named in the environment. A playbook
# there is self-contained: it only touches objects named roletest-..., and
# removes them before it starts and when it ends, so the playbooks can run in
# any order on one server.
# Usage: role-test.sh <collection> [ansible-playbook options]   (from the repository root)
# Needs ansible-core on the PATH, and for semaphoreui SEMAPHORE_URL with
# SEMAPHORE_USERNAME and SEMAPHORE_PASSWORD (or SEMAPHORE_API_TOKEN). The
# modules read those themselves. Throwaway servers only.
set -euo pipefail

collection="${1:?usage: role-test.sh <collection> [ansible-playbook options]}"
shift
namespace=ramanavelineni
tests_dir="ansible_collections/${namespace}/${collection}/tests/roles"
test -f "ansible_collections/${namespace}/${collection}/galaxy.yml" \
  || { echo "no collection at ansible_collections/${namespace}/${collection}" >&2; exit 1; }

shopt -s nullglob
playbooks=("${tests_dir}"/*.yml)
if [ "${#playbooks[@]}" -eq 0 ]; then
  echo "${collection} has no role tests (${tests_dir}/*.yml)"
  exit 0
fi

case "${collection}" in
  semaphoreui) server="${SEMAPHORE_URL:-}"; variable=SEMAPHORE_URL ;;
  harbor) server="${HARBOR_URL:-}"; variable=HARBOR_URL ;;
  *) server=unknown; variable='' ;;
esac
if [ -z "${server}" ]; then
  echo "set ${variable} (and the credentials) to a throwaway server; the role tests create and delete objects" >&2
  exit 1
fi

# The repository root has ansible_collections/ in it, so it is a collections
# path: the roles and modules are used from the checkout, not from a build.
ANSIBLE_COLLECTIONS_PATH="$(pwd)${ANSIBLE_COLLECTIONS_PATH:+:${ANSIBLE_COLLECTIONS_PATH}}"
export ANSIBLE_COLLECTIONS_PATH
# The playbooks run on the implicit localhost; no inventory is wanted.
export ANSIBLE_LOCALHOST_WARNING=false ANSIBLE_INVENTORY_UNPARSED_WARNING=false

for playbook in "${playbooks[@]}"; do
  echo "== ${playbook}"
  ansible-playbook "${playbook}" "$@"
done
echo "== ${#playbooks[@]} role test playbook(s) passed"
