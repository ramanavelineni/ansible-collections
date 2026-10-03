# ramanavelineni.harbor

**Configure [Harbor](https://goharbor.io) as code.** Projects, robot accounts,
registries, replication, retention and immutability rules, webhooks and system
settings, each described once and kept that way.

[![CI](https://github.com/ramanavelineni/ansible-collections/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ramanavelineni/ansible-collections/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/ramanavelineni/ansible-collections/blob/main/LICENSE)
![ansible-core 2.18–2.21](https://img.shields.io/badge/ansible--core-2.18%20%E2%80%93%202.21-EE0000?logo=ansible)
![Harbor 2.14 | 2.15](https://img.shields.io/badge/Harbor-2.14%20%7C%202.15-60B932)

Every module finds its object **by name**, changes only what differs from the
options you set, and supports **check mode and `--diff`**. Objects refer to
each other by name: a replication rule's `src_registry: dockerhub`, a robot
account's `project: apps`.

## Install

In `requirements.yml` (no Galaxy account needed):

```yaml
collections:
  - name: https://github.com/ramanavelineni/ansible-collections.git#/ansible_collections/ramanavelineni/harbor
    type: git
    version: harbor-v0.2.0
```

```sh
ansible-galaxy collection install -r requirements.yml
```

Needs ansible-core 2.18 or newer and Harbor 2.14 or 2.15. Other versions work
but print a warning on every task; `warn_untested_version: false` turns it off.

## Example

```yaml
- hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.harbor.harbor:
      url: https://harbor.example.com
      username: admin
      password: "{{ harbor_admin_password }}"
  tasks:
    - name: Docker Hub as an upstream
      ramanavelineni.harbor.registry:
        name: dockerhub
        type: docker-hub
        endpoint_url: https://hub.docker.com

    - name: Pull-through cache of Docker Hub
      ramanavelineni.harbor.project:
        name: proxy-docker
        public: true
        proxy_registry: dockerhub

    - name: Private project, scanned on push, 50 GiB quota
      ramanavelineni.harbor.project:
        name: apps
        metadata:
          auto_scan: true
          severity: high
          prevent_vul: true
        quota_gb: 50

    - name: Keep the 10 newest artifacts per repository, pruned nightly
      ramanavelineni.harbor.tag_retention:
        project: apps
        schedule: "0 0 3 * * *"
        rules:
          - template: latestPushedK
            value: 10

    - name: CI robot that can push to apps
      ramanavelineni.harbor.robot_account:
        name: ci
        level: project
        project: apps
        permissions:
          - access:
              - {resource: repository, action: pull}
              - {resource: repository, action: push}
      register: ci_robot
      no_log: true   # a new robot's generated secret is in the result

    - name: Weekly garbage collection
      ramanavelineni.harbor.garbage_collection:
        schedule: custom
        cron: "0 0 4 * * 0"
        delete_untagged: true
```

Run it with `--check --diff` first to see what would change.

## Modules

| Area | Module | Read-only |
|---|---|---|
| Server | | `info`: version, tested flag |
| Projects | `project`: visibility, metadata, proxy cache, quota | `project_info` |
| Robot accounts | `robot_account`: system or project level | `robot_account_info` |
| Registries (endpoints) | `registry` | `registry_info` |
| Replication rules | `replication`: pull or push, trigger, filters | `replication_info` |
| Webhooks | `webhook` | `webhook_info` |
| Tag retention | `tag_retention`: rules and schedule | `tag_retention_info` |
| Tag immutability | `tag_immutability`: one rule per task | `tag_immutability_info` |
| Configuration | `configuration`: auth, OIDC, LDAP and other settings | `configuration_info` |
| Garbage collection | `garbage_collection`: schedule | `garbage_collection_info` |
| Vulnerability scan all | `scan_all`: schedule | `scan_all_info` |
| Audit log rotation | `log_rotation`: schedule and retention | `log_rotation_info` |

Full documentation for each: `ansible-doc ramanavelineni.harbor.<module>`.

## Connecting

Harbor's API only takes HTTP basic authentication, so each module takes `url`
(with or without `/api/v2.0`), `username` and `password`. That can be an
administrator, an ordinary user, a robot account (`robot$name` and its secret)
or an OIDC user with their CLI secret. Set them once per play with the action
group `group/ramanavelineni.harbor.harbor`, as in the example, or through
environment variables:

| Option | Environment variable |
|---|---|
| `url` | `HARBOR_URL` |
| `username` / `password` | `HARBOR_USERNAME` / `HARBOR_PASSWORD` |
| `validate_certs` / `ca_path` | `HARBOR_VALIDATE_CERTS` / `HARBOR_CA_PATH` |
| `client_cert` / `client_key` | `HARBOR_CLIENT_CERT` / `HARBOR_CLIENT_KEY` |
| `use_proxy` | `HARBOR_USE_PROXY` |
| `warn_untested_version` | `HARBOR_WARN_UNTESTED_VERSION` |

For a server that asks for a TLS client certificate (mutual TLS), `client_cert`
is the PEM file with the certificate and `client_key` the one with its key;
`client_key` isn't needed when the certificate file holds the key too. Both are
read on the host the module runs on.

The proxy from `http_proxy`, `https_proxy` and `no_proxy` is used when set;
`use_proxy: false` goes to the server directly. Redirects are never followed,
so `url` has to be the address Harbor itself answers on; a failure on a
redirect names the target.

**Wrong credentials don't always fail in Harbor.** Harbor answers many requests
as an anonymous user instead, so every module checks the login first. Harbor
also locks a user for 1.5 s after a failed login. A module that hits the lock
waits and tries once more, but automation that shares one account with
something else that might fail to log in is better off with its own account.

## Good to know

<details>
<summary><b>Secrets</b> (<code>robot_account</code>, <code>registry</code>, <code>configuration</code>)</summary>

Harbor never returns a stored secret, so a changed secret can't be detected.
`update_secret: always` (the default) sends the declared secret on every run
and reports a change; `on_create` sends it only when the object is created.

- `robot_account`: without a declared secret, Harbor generates one, which is
  returned once when the robot is created. Register the task with
  `no_log: true`.
- `configuration`: `oidc_client_secret` and `ldap_search_password` are separate
  options, never keys in `settings`, so they're never printed.
- `webhook`: Harbor *does* return the auth header, so it's only sent when it
  differs; it's still never in the module's output.

</details>

<details>
<summary><b>Projects, registries, replication</b></summary>

- `project` checks metadata keys and values before sending them, because
  Harbor silently drops unknown keys and stores an invalid severity as
  `unknown`. A project's proxy-cache registry can only be set when it's
  created.
- `registry`: Harbor checks that an endpoint is reachable whenever it's
  created or changed. An endpoint's type can't be changed, so a different
  type fails with instructions to recreate it.
- `replication` checks cron expressions (6 fields, seconds `0`) and filters
  before sending anything.

</details>

<details>
<summary><b>Retention, immutability, schedules</b></summary>

- `tag_retention` manages a project's single policy, and its `rules` are the
  complete list. It never starts a retention run.
- `tag_immutability` manages one rule per task, identified by its patterns.
- `garbage_collection`, `scan_all` and `log_rotation` only manage schedules.
  They never start a run. `scan_all` needs a vulnerability scanner installed
  in Harbor.

</details>

<details>
<summary><b>Configuration</b></summary>

`configuration` takes a `settings` dict of Harbor's own setting names and
sends only those that differ. Unknown keys and wrong types fail before
anything is sent, because Harbor would silently ignore or reject them.
`auth_mode` can only change while no user other than the admin exists. A
setting Harbor reports as not editable fails the task by name before anything
is sent, unless the declared value is already in place.

Neither `configuration` nor `configuration_info` returns a secret. Besides the
secrets they know, they leave out any key they have no name for whose name
contains `secret`, `password`, `passwd`, `token`, `credential` or
`private_key`, in case a newer Harbor returns one.

</details>

## More

- [Repository and other collections](https://github.com/ramanavelineni/ansible-collections)
- [Design notes and every Harbor API quirk found](https://github.com/ramanavelineni/ansible-collections/blob/main/PLAN.md)
- [Changelog](https://github.com/ramanavelineni/ansible-collections/blob/main/ansible_collections/ramanavelineni/harbor/CHANGELOG.md)

Apache-2.0 licensed.
