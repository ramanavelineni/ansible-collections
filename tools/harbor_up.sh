#!/usr/bin/env bash
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)
#
# Starts a throwaway Harbor for tools/record_harbor_fixtures.py and takes it
# away again. One Harbor per tested version, each on its own port:
#
#   tools/harbor_up.sh up v2.15.2 8015
#   tools/harbor_up.sh down v2.15.2
#
# It does what the Harbor servers the committed fixtures were recorded from
# were set up with, under rootless podman:
#
#   1. Harbor's harbor.yml.tmpl of that version, edited for plain HTTP, a lab
#      host name, generated passwords and a data directory of its own.
#   2. Harbor's own "prepare" container, which writes the configuration of
#      every service and a docker-compose.yml.
#   3. That docker-compose.yml adjusted (see adjust_compose below for what and
#      why), and started as a compose project named harbor<version>.
#
# Everything lives in $HARBOR_UP_DIR/<version> (default: ~/harbor-lab), the
# data too, so "down" leaves nothing behind.
#
# Run it where the containers run: on Linux as it is; with a podman machine
# (macOS), inside the machine, because the data must not sit on the shared
# host file system:
#
#   podman machine ssh 'bash -s -- up v2.15.2 8015' < tools/harbor_up.sh
#   HARBOR_PASSWORD="$(podman machine ssh cat harbor-lab/v2.15.2/admin_password)" \
#       tools/record_harbor_fixtures.py http://127.0.0.1:8015
#
# A port published in the machine on 127.0.0.1 is reachable on the host, so
# the recorder runs on the host. The admin password is generated and stored
# in <dir>/admin_password (mode 600); this script prints where, never the
# password.
#
# Needs: bash, curl, sed, awk, podman or docker, and a compose command
# ("podman compose" with a provider installed, "docker compose",
# "podman-compose" or "docker-compose").
#
# WHAT IS PROVEN AND WHAT IS NOT. The two edits this script makes itself are
# tested without a server (tools/tests/test_harbor_up.py): the edited
# harbor.yml, and the adjusted docker-compose.yml, which for 2.14.4 and 2.15.2
# equals the compose file of the working servers. Starting and stopping a
# stack with this script has NOT been run end to end yet: the prepare call,
# the compose command found on the machine, the wait and the removal of the
# data are written from Harbor's own prepare script and from the working
# setup, and are the parts to watch on the first run. Take this paragraph out
# after that run.

set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: harbor_up.sh up <version> [port]     start a throwaway Harbor (port default 8015)
       harbor_up.sh down <version>          stop it and remove its directory
<version> is a Harbor release tag such as v2.15.2.
With a podman machine: podman machine ssh 'bash -s -- up v2.15.2 8015' < tools/harbor_up.sh
EOF
  exit 2
}

die() {
  echo "harbor_up: $*" >&2
  exit 1
}

# harbor.yml.tmpl on stdin, harbor.yml on stdout.
#   - hostname: Harbor's template says not to use localhost or 127.0.0.1.
#   - http.port 8080: the port the proxy listens on inside the compose
#     network. The published port is set in the compose file instead.
#   - the https block is taken out: plain HTTP.
#   - the two passwords and the data directory.
edit_config() {
  local hostname="$1" data="$2" admin_password="$3" db_password="$4" out
  out="$(sed \
    -e "s|^hostname: .*|hostname: ${hostname}|" \
    -e '/^http:/,/^$/ s|^\(  port: \)80$|\18080|' \
    -e '/^https:/,/^$/d' \
    -e "s|^harbor_admin_password: .*|harbor_admin_password: ${admin_password}|" \
    -e "/^database:/,/^\$/ s|^\(  password: \).*|\1${db_password}|" \
    -e "s|^data_volume: .*|data_volume: ${data}|")"
  # The template may change between versions; rather stop than start a Harbor
  # that is configured differently from what was meant.
  local line
  for line in "hostname: ${hostname}" '  port: 8080' "harbor_admin_password: ${admin_password}" \
              "  password: ${db_password}" "data_volume: ${data}"; do
    printf '%s\n' "${out}" | grep -qxF -- "${line}" \
      || die "harbor.yml.tmpl has changed: no line '${line%%:*}:' where this script expects one"
  done
  if printf '%s\n' "${out}" | grep -q '^https:'; then
    die 'harbor.yml.tmpl has changed: the https block could not be taken out'
  fi
  printf '%s\n' "${out}"
}

# The docker-compose.yml that prepare wrote on stdin, the adjusted one on
# stdout. Adjustments, each as in the working setup:
#   - No "log" service, no "logging:" blocks, no "depends_on: log". Harbor
#     sends every container's log to its log container through docker's
#     syslog log driver, which podman does not have.
#   - No "container_name:". The fixed names (nginx, registry, redis, ...)
#     would clash between two Harbor versions running side by side; without
#     them the names come from the compose project.
#   - "security_opt: label=disable" on every service. Several mounts in the
#     file are "type: bind" without a relabel option, which SELinux (enforcing
#     in a podman machine) would keep the containers from reading.
#   - redis: docker.io/valkey/valkey:8-alpine with its own start command, and
#     without Harbor's cap_drop/cap_add, in place of Harbor's redis image.
#     Adjustment observed in the working setup, reason not established.
#   - The proxy's port is published on 127.0.0.1 only, on the chosen port. A
#     throwaway is still nothing to expose.
adjust_compose() {
  local port="$1"
  awk -v port="${port}" '
    function flush(    i, n, line, skip, deps, ndeps, out, nout, k) {
      if (name == "") return
      if (name == "log") { seen_log = 1; name = ""; nbuf = 0; return }
      nout = 0; skip = ""
      for (i = 1; i <= nbuf; i++) {
        line = buf[i]
        if (line ~ /^[ \t]*$/) continue
        if (skip != "") {
          if (line ~ /^      /) {
            if (skip == "depends_on" && line !~ /^      - log$/) deps[++ndeps] = line
            continue
          }
          if (skip == "depends_on" && ndeps > 0) {
            out[++nout] = "    depends_on:"
            for (k = 1; k <= ndeps; k++) out[++nout] = deps[k]
          }
          skip = ""
        }
        if (line ~ /^    container_name:/) continue
        if (line ~ /^    logging:$/) { skip = "logging"; removed_logging++; continue }
        if (line ~ /^    depends_on:$/) { skip = "depends_on"; ndeps = 0; continue }
        if (name == "redis") {
          if (line ~ /^    image:/) { line = "    image: docker.io/valkey/valkey:8-alpine"; seen_redis = 1 }
          if (line ~ /^    cap_(drop|add):$/) { skip = "caps"; continue }
        }
        if (name == "proxy" && line ~ /^      - [0-9]+:8080$/) {
          line = "      - 127.0.0.1:" port ":8080"; seen_port = 1
        }
        out[++nout] = line
      }
      if (skip == "depends_on" && ndeps > 0) {
        out[++nout] = "    depends_on:"
        for (k = 1; k <= ndeps; k++) out[++nout] = deps[k]
      }
      for (i = 1; i <= nout; i++) print out[i]
      print "    security_opt:"
      print "      - label=disable"
      if (name == "redis") {
        print "    command:"
        print "      - valkey-server"
        print "      - --dir"
        print "      - /var/lib/redis"
      }
      name = ""; nbuf = 0
    }
    /^services:$/ { in_services = 1; print; next }
    in_services && /^[^ ]/ { flush(); in_services = 0 }
    in_services && /^  [A-Za-z0-9_-]+:$/ {
      flush()
      name = $1; sub(/:$/, "", name)
      buf[++nbuf] = $0
      next
    }
    in_services { buf[++nbuf] = $0; next }
    { print }
    END {
      if (in_services) flush()
      if (!seen_log) { print "harbor_up: no log service in docker-compose.yml" > "/dev/stderr"; bad = 1 }
      if (!removed_logging) { print "harbor_up: no logging block in docker-compose.yml" > "/dev/stderr"; bad = 1 }
      if (!seen_redis) { print "harbor_up: no redis image in docker-compose.yml" > "/dev/stderr"; bad = 1 }
      if (!seen_port) { print "harbor_up: no port 8080 of the proxy in docker-compose.yml" > "/dev/stderr"; bad = 1 }
      exit bad
    }
  '
}

engine() {
  if command -v podman >/dev/null 2>&1; then
    echo podman
  elif command -v docker >/dev/null 2>&1; then
    echo docker
  else
    die 'neither podman nor docker is installed'
  fi
}

# Sets the array "compose" to the compose command of this machine.
find_compose() {
  if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
    compose=(podman compose)
  elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
  elif command -v podman-compose >/dev/null 2>&1; then
    compose=(podman-compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    compose=(docker-compose)
  else
    die 'no compose command found: install a provider for "podman compose" (docker-compose or podman-compose), or docker with its compose plugin'
  fi
}

random_hex() {
  head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

up() {
  local eng tmpl i
  local -a compose
  [ ! -e "${dir}" ] || die "${dir} exists already; run 'down ${version}' first"
  eng="$(engine)"
  find_compose

  # The services run as users of their own and have to get into the data and
  # configuration directories, so those are not closed to others. What holds
  # a password is: the admin password file and input/, with harbor.yml.
  umask 022
  mkdir -p "${dir}/data" "${dir}/common/config"
  mkdir -m 700 "${dir}/input"
  # "down" removes a directory only if this file is in it.
  echo "${version}" > "${dir}/.harbor_up"
  # Upper case, lower case and digits, whatever the random part holds.
  (umask 077 && printf 'Hb1%s\n' "$(random_hex)" > "${dir}/admin_password")

  tmpl="https://raw.githubusercontent.com/goharbor/harbor/${version}/make/harbor.yml.tmpl"
  curl -fsSL "${tmpl}" \
    | edit_config "harbor-${version//./}.lab" "${dir}/data" "$(cat "${dir}/admin_password")" "$(random_hex)" \
    > "${dir}/input/harbor.yml"

  # Harbor's prepare script runs this container with the same four mounts. It
  # also mounts the host's root as /hostfs, which prepare reads only for TLS
  # certificates and a custom CA bundle; neither is used here, so it is left
  # out. prepare writes files as the users the services run as.
  "${eng}" run --rm --privileged \
    -v "${dir}/input:/input" \
    -v "${dir}/data:/data" \
    -v "${dir}:/compose_location" \
    -v "${dir}/common/config:/config" \
    "docker.io/goharbor/prepare:${version}" prepare

  mv "${dir}/docker-compose.yml" "${dir}/docker-compose.prepare.yml"
  adjust_compose "${port}" < "${dir}/docker-compose.prepare.yml" > "${dir}/docker-compose.yml"

  (cd "${dir}" && "${compose[@]}" -p "${project}" -f docker-compose.yml up -d)

  echo "waiting for Harbor on http://127.0.0.1:${port} ..."
  for i in $(seq 1 60); do
    # The admin's own account answers 200 only when core and the database
    # are up; /systeminfo answers earlier.
    if curl -fsS -o /dev/null -u "admin:$(cat "${dir}/admin_password")" \
         "http://127.0.0.1:${port}/api/v2.0/users/current" 2>/dev/null; then
      echo "Harbor ${version} is up: http://127.0.0.1:${port}"
      echo "user admin, password in ${dir}/admin_password"
      return 0
    fi
    sleep 5
  done
  die "Harbor did not answer within 5 minutes (try ${i} of 60); see '${compose[*]} -p ${project} logs' in ${dir}"
}

down() {
  local eng
  local -a compose
  [ -e "${dir}" ] || die "${dir} does not exist"
  [ -f "${dir}/.harbor_up" ] || die "${dir} was not made by this script (no .harbor_up in it); not touching it"
  eng="$(engine)"
  if [ -f "${dir}/docker-compose.yml" ]; then
    find_compose
    (cd "${dir}" && "${compose[@]}" -p "${project}" -f docker-compose.yml down -v)
  fi
  # prepare and the services wrote files as other users. Under rootless
  # podman those are ids of this user's own range, which "podman unshare" may
  # remove; under docker they are real users, and removing them takes root.
  if [ "${eng}" = podman ] && [ "$(podman info --format '{{.Host.Security.Rootless}}')" = true ]; then
    podman unshare rm -rf "${dir}"
  else
    rm -rf "${dir}" || die "could not remove ${dir}; remove it as root"
  fi
  echo "removed ${dir}"
}

main() {
  [ $# -ge 1 ] || usage
  local action="$1"
  case "${action}" in
    # The two edits alone, stdin to stdout, for the tests.
    edit-config) [ $# -eq 5 ] || usage; edit_config "$2" "$3" "$4" "$5"; return ;;
    adjust-compose) [ $# -eq 2 ] || usage; adjust_compose "$2"; return ;;
  esac
  [ $# -ge 2 ] || usage
  version="$2"
  port="${3:-8015}"
  case "${version}" in
    v[0-9]*.[0-9]*.[0-9]*) ;;
    *) die "version must look like v2.15.2, got '${version}'" ;;
  esac
  case "${port}" in
    ''|*[!0-9]*) die "port must be a number, got '${port}'" ;;
  esac
  dir="${HARBOR_UP_DIR:-${HOME}/harbor-lab}/${version}"
  project="harbor${version//./}"
  case "${action}" in
    up) up ;;
    down) down ;;
    *) usage ;;
  esac
}

main "$@"
