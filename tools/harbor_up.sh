#!/usr/bin/env bash
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)
#
# NOT YET RUN. This script was written from Harbor's installation guide
# (https://goharbor.io/docs/latest/install-config/) without a Harbor at hand.
# Run it step by step the first time, fix what is wrong, and take this notice
# out. The steps marked TODO are the ones to look at first.
#
# Starts a throwaway Harbor for tools/record_harbor_fixtures.py, with Harbor's
# own online installer, on plain HTTP on a local port:
#
#   HARBOR_PASSWORD=<password> tools/harbor_up.sh up v2.15.0 8015
#   HARBOR_PASSWORD=<password> tools/record_harbor_fixtures.py http://127.0.0.1:8015
#   tools/harbor_up.sh down v2.15.0
#
# One Harbor per tested version; give each its own port. Everything lives
# under $HARBOR_UP_DIR/<version> (default: ~/.cache/harbor-up), also the
# data, so "down" leaves nothing behind.
#
# Needs: Linux, docker with the compose plugin, curl, tar, sed.
# TODO(verify): the installer is made for Linux. On macOS (Docker Desktop,
# podman machine) it is not expected to work as it is: the log container
# binds a syslog port on the host and the data directory is mounted from it.

set -euo pipefail

usage() {
  sed -n 's/^#   //p' "$0"
  exit 2
}

[ $# -ge 2 ] || usage
action="$1"
version="$2"
port="${3:-8015}"
base="${HARBOR_UP_DIR:-${HOME}/.cache/harbor-up}"
dir="${base}/${version}"

case "${version}" in
  v[0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "version must look like v2.15.0, got '${version}'" >&2; exit 2 ;;
esac

down() {
  if [ -f "${dir}/harbor/docker-compose.yml" ]; then
    # -v also removes the volumes the compose file declares.
    (cd "${dir}/harbor" && docker compose down -v)
  fi
  # TODO(verify): the containers write the data directory as other users, so
  # removing it may need root. If this fails, remove ${dir} with sudo.
  rm -rf "${dir}"
}

up() {
  : "${HARBOR_PASSWORD:?set HARBOR_PASSWORD to the admin password the throwaway Harbor gets}"
  if [ -e "${dir}" ]; then
    echo "${dir} exists already; run '$0 down ${version}' first" >&2
    exit 1
  fi
  mkdir -p "${dir}/data" "${dir}/log"
  cd "${dir}"

  # The online installer is small and pulls the images when it runs.
  curl -fsSL -o installer.tgz \
    "https://github.com/goharbor/harbor/releases/download/${version}/harbor-online-installer-${version}.tgz"
  tar -xzf installer.tgz   # unpacks into ./harbor
  cd harbor
  cp harbor.yml.tmpl harbor.yml

  # hostname: Harbor's template says not to use localhost or 127.0.0.1 here.
  # The recorder talks to 127.0.0.1:<port> whatever this is set to.
  # TODO(verify): that the API on 127.0.0.1:<port> answers with a hostname
  # that differs from the address used.
  sed -i.bak \
    -e "s|^hostname: .*|hostname: $(hostname)|" \
    -e "s|^harbor_admin_password: .*|harbor_admin_password: ${HARBOR_PASSWORD}|" \
    -e "s|^data_volume: .*|data_volume: ${dir}/data|" \
    -e "s|^\( *location: \)/var/log/harbor|\1${dir}/log|" \
    harbor.yml
  # Plain HTTP on the chosen port: set http.port, and comment the https block out.
  # TODO(verify): the two patterns below against the harbor.yml.tmpl of the
  # version at hand: "  port: 80" under "http:", and the "https:" block ending
  # with its "private_key:" line.
  sed -i.bak \
    -e "/^http:/,/^[^ #]/ s|^\( *port: \)80\$|\1${port}|" \
    -e '/^https:/,/^ *private_key:/ s|^|# |' \
    harbor.yml
  rm -f harbor.yml.bak

  # TODO(verify): whether the installer needs root on the machine at hand
  # (it writes under data_volume and the log location, which are set to
  # directories of the calling user above).
  ./install.sh

  # TODO(verify): the installer publishes the port on every interface. A
  # throwaway is still not something to expose; restrict it in the generated
  # docker-compose.yml (proxy service, "ports:") if the machine is reachable.

  echo "waiting for Harbor on http://127.0.0.1:${port} ..."
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null "http://127.0.0.1:${port}/api/v2.0/systeminfo"; then
      echo "Harbor ${version} is up: http://127.0.0.1:${port} (user admin)"
      # The registry area makes Harbor ping itself as http://proxy:8080: "proxy"
      # is the name of the installer's nginx service, which listens on 8080
      # inside the compose network.
      # TODO(verify): that name and port in the generated docker-compose.yml
      # (service "proxy", "ports: - <port>:8080"). If they differ, the two
      # endpoints in record_registry() have to follow.
      return 0
    fi
    sleep 5
  done
  echo "Harbor did not answer within 5 minutes; see 'docker compose logs' in ${dir}/harbor" >&2
  exit 1
}

case "${action}" in
  up) up ;;
  down) down ;;
  *) usage ;;
esac
