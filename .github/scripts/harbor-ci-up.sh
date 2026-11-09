#!/usr/bin/env bash
# Installs a throwaway Harbor on a CI runner from Harbor's offline installer,
# for the harbor collection's role tests. Plain HTTP on 127.0.0.1:8080.
# Usage: harbor-ci-up.sh <version> <download directory>   (from the repository root)
# Needs HARBOR_PASSWORD (the admin password to set), docker with the compose
# plugin, and sudo. Writes the time each step took to $GITHUB_STEP_SUMMARY
# when that is set.
#
# The installer is checked against the SHA-256 pinned below before anything in
# it runs, also when it comes from the cache. The values are the digests
# GitHub recorded for the release assets of goharbor/harbor:
#   gh api repos/goharbor/harbor/releases/tags/<version> \
#     --jq '.assets[] | select(.name|test("offline-installer.*tgz$")) | .digest'
# A version that isn't listed here is refused.
set -euo pipefail

version="${1:?usage: harbor-ci-up.sh <version> <download directory>}"
downloads="${2:?usage: harbor-ci-up.sh <version> <download directory>}"
: "${HARBOR_PASSWORD:?set HARBOR_PASSWORD to the admin password to give the new Harbor}"

case "${version}" in
  v2.14.6) sha256=f3adaff30c4531c58f9d6ee8c5164f95f08582651c12b698b92be9e98df55cf6 ;;
  v2.15.4) sha256=ec4152a644cedc627c747b84e91ba0f44c1d44576b43b8d1f73e2e51b3b5ccfc ;;
  *) echo "harbor-ci-up: no pinned SHA-256 for Harbor ${version}; add it to this script" >&2; exit 1 ;;
esac

root="$(pwd)"
name="harbor-offline-installer-${version}.tgz"
tarball="${downloads}/${name}"
work="${RUNNER_TEMP:-/tmp}/harbor-${version}"
started="$(date +%s)"
step_started="${started}"
summary=()

timed() {  # timed <what>: note how long the step since the last note took
  local now
  now="$(date +%s)"
  summary+=("| ${1} | $((now - step_started)) s |")
  echo "harbor-ci-up: ${1} took $((now - step_started)) s"
  step_started="${now}"
}

mkdir -p "${downloads}"
if [ -f "${tarball}" ]; then
  echo "harbor-ci-up: ${name} from the cache"
else
  curl -fsSL --retry 3 -o "${tarball}.part" \
    "https://github.com/goharbor/harbor/releases/download/${version}/${name}"
  mv "${tarball}.part" "${tarball}"
fi
timed "download (or cache)"

if ! echo "${sha256}  ${tarball}" | sha256sum -c --quiet -; then
  # A bad file must not stay in the cache and fail every later run.
  rm -f "${tarball}"
  echo "harbor-ci-up: ${name} does not have the pinned SHA-256 ${sha256}" >&2
  exit 1
fi
timed "SHA-256 check"

rm -rf "${work}"
mkdir -p "${work}/data"
tar xzf "${tarball}" -C "${work}"
timed "unpack"

# The same edits tools/harbor_up.sh makes for the throwaway servers behind the
# fixtures (tested by tools/tests/test_harbor_up.py): plain HTTP on port 8080,
# the admin and database passwords, and the data directory.
bash "${root}/tools/harbor_up.sh" edit-config harbor-ci.lab "${work}/data" "${HARBOR_PASSWORD}" \
  "db-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')" \
  < "${work}/harbor/harbor.yml.tmpl" > "${work}/harbor/harbor.yml"
(cd "${work}/harbor" && sudo ./install.sh)
timed "install.sh (load images, prepare, start)"

# The admin's own account answers 200 only when core and the database are up;
# /systeminfo answers earlier.
for try in $(seq 1 60); do
  if curl -fsS -o /dev/null -u "admin:${HARBOR_PASSWORD}" http://127.0.0.1:8080/api/v2.0/users/current; then
    timed "until the API answers as admin"
    break
  fi
  if [ "${try}" -eq 60 ]; then
    echo "harbor-ci-up: Harbor did not answer as admin within 5 minutes" >&2
    (cd "${work}/harbor" && sudo docker compose ps) || true
    exit 1
  fi
  sleep 5
done

total="$(( $(date +%s) - started ))"
echo "harbor-ci-up: Harbor ${version} is up on http://127.0.0.1:8080 after ${total} s"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Harbor ${version} install"
    echo
    echo "| Step | Time |"
    echo "|---|---|"
    printf '%s\n' "${summary[@]}"
    echo "| **total** | **${total} s** |"
    echo
  } >> "${GITHUB_STEP_SUMMARY}"
fi
