#!/usr/bin/env bash
# Builds a collection's tarball, installs it into an empty directory and uses
# it from there, the way someone who downloaded a release would:
#   - the tarball has the LICENSE and no file that looks like a secret
#   - ansible-doc renders every module from the installed copy
#   - one module runs from it: `info` against a port where nothing listens must
#     fail with the collection's own connection error, which proves the module
#     and its module_utils import from the installed tarball
# Usage: install-test.sh <collection>     (from the repository root)
# Needs ansible-core on the PATH. SKIP_RUN=1 leaves the module run out, for
# sandboxes in which Ansible cannot start worker processes.
set -euo pipefail

collection="${1:?usage: install-test.sh <collection>}"
namespace=ramanavelineni
source_dir="ansible_collections/${namespace}/${collection}"
test -f "${source_dir}/galaxy.yml" || { echo "no collection at ${source_dir}" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

echo "== build"
ansible-galaxy collection build "${source_dir}" --output-path "${work}/dist"
tarball="$(ls "${work}"/dist/*.tar.gz)"

echo "== tarball contents"
tar -tzf "${tarball}" > "${work}/files.txt"
grep -qx 'LICENSE' "${work}/files.txt" || { echo "the tarball has no LICENSE" >&2; exit 1; }
# Names a secret scan would flag. Module and test names such as key_store.py
# don't match: only whole extensions and dot-env files do.
if grep -E '(^|/)\.env(\.|$)|\.(pem|key|p12|pfx)$|(^|/)id_(rsa|ed25519|ecdsa)$' "${work}/files.txt"; then
  echo "the tarball contains the files above, which look like secrets" >&2
  exit 1
fi
echo "$(wc -l < "${work}/files.txt" | tr -d ' ') entries, LICENSE present, no secret-like names"

echo "== install"
ansible-galaxy collection install "${tarball}" -p "${work}/collections"
installed="${work}/collections/ansible_collections/${namespace}/${collection}"
test -f "${installed}/MANIFEST.json" || { echo "nothing installed at ${installed}" >&2; exit 1; }

# From here on, only the installed copy: an empty working directory and a
# collections path that doesn't include the checkout.
mkdir "${work}/empty"
cd "${work}/empty"
export ANSIBLE_COLLECTIONS_PATH="${work}/collections"
export ANSIBLE_LOCAL_TEMP="${work}/tmp"
export ANSIBLE_NOCOLOR=1

echo "== ansible-doc"
count=0
for file in "${installed}"/plugins/modules/*.py; do
  module="$(basename "${file}" .py)"
  ansible-doc -t module "${namespace}.${collection}.${module}" > "${work}/doc.txt" || {
    echo "ansible-doc failed for ${module}" >&2; exit 1; }
  grep -q "${installed}" "${work}/doc.txt" || {
    echo "ansible-doc showed ${module} from somewhere else than the installed copy" >&2; exit 1; }
  count=$((count + 1))
done
echo "${count} modules documented from the installed copy"

if [ "${SKIP_RUN:-}" = 1 ]; then
  echo "== run a module: skipped (SKIP_RUN=1)"
  exit 0
fi

echo "== run a module"
case "${collection}" in
  semaphoreui) args='url=http://127.0.0.1:9 api_token=install-test-token retries=0' ;;
  harbor)      args='url=http://127.0.0.1:9 username=install-test password=install-test-password retries=0' ;;
  *) echo "no module arguments known for ${collection}" >&2; exit 1 ;;
esac
status=0
ansible localhost -m "${namespace}.${collection}.info" -a "${args}" > "${work}/run.txt" 2>&1 || status=$?
cat "${work}/run.txt"
# The module must have started and failed in the collection's own client. A
# missing module, an import error or a traceback would say something else.
if [ "${status}" -eq 0 ]; then
  echo "the module succeeded against a port where nothing listens" >&2; exit 1
fi
grep -q 'failed without an HTTP response' "${work}/run.txt" || {
  echo "the module did not fail with the collection's connection error" >&2; exit 1; }
if grep -qE 'Traceback|MODULE FAILURE|was not found|couldn.t resolve' "${work}/run.txt"; then
  echo "the module failed before it reached the collection's client" >&2; exit 1
fi
echo "info ran from the installed copy and failed with the collection's connection error"
