# ansible-collections

**Declarative Ansible modules for Semaphore UI and Harbor.** Describe what you
want: projects, keys, templates, robot accounts, retention rules. The modules
make the server match, and change nothing when it already does.

[![CI](https://github.com/ramanavelineni/ansible-collections/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ramanavelineni/ansible-collections/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
![ansible-core 2.18–2.21](https://img.shields.io/badge/ansible--core-2.18%20%E2%80%93%202.21-EE0000?logo=ansible)
![Semaphore UI 2.18 | 2.19](https://img.shields.io/badge/Semaphore%20UI-2.18%20%7C%202.19-7B42BC)
![Harbor 2.14 | 2.15](https://img.shields.io/badge/Harbor-2.14%20%7C%202.15-60B932)

| Collection | Configures | Modules | Tested with |
|---|---|---|---|
| [**`ramanavelineni.semaphoreui`**](ansible_collections/ramanavelineni/semaphoreui/) | [Semaphore UI](https://semaphoreui.com): projects and everything in them, users, runners | 25 | Semaphore UI 2.18, 2.19 |
| [**`ramanavelineni.harbor`**](ansible_collections/ramanavelineni/harbor/) | [Harbor](https://goharbor.io): projects, robot accounts, registries, replication, policies, system settings | 23 | Harbor 2.14, 2.15 |

---

## Why

Managing these servers from Ansible usually means `ansible.builtin.uri`
tasks: list the objects, look one up by name, create it if it's missing,
compare it field by field, then send an update. That's repeated for every
kind of object and every API quirk. These collections do that work inside
the modules.

<table>
<tr><th>Before: raw API calls</th><th>After: one module</th></tr>
<tr>
<td>

```yaml
- name: Read the project's repositories
  ansible.builtin.uri:
    url: "{{ api }}/project/{{ pid }}/repositories"
    headers: {Cookie: "{{ session }}"}
  register: repos

- name: Find ours by name
  ansible.builtin.set_fact:
    repo: >-
      {{ repos.json | selectattr('name', 'eq', 'ansible')
         | first | default(none) }}

- name: Create it when missing
  ansible.builtin.uri:
    url: "{{ api }}/project/{{ pid }}/repositories"
    method: POST
    headers: {Cookie: "{{ session }}"}
    body_format: json
    body: {project_id: "{{ pid | int }}", name: ansible,
           git_url: "{{ git_url }}", git_branch: main,
           ssh_key_id: "{{ key_ids['deploy'] | int }}"}
    status_code: [201]
  when: repo is none

- name: Update it when it drifted
  ansible.builtin.uri: ...   # compare, rebuild the body, PUT
  when: repo is not none and ...
```

</td>
<td>

```yaml
- name: The ansible repository
  ramanavelineni.semaphoreui.repository:
    project: homelab
    name: ansible
    git_url: git@github.com:example/ansible.git
    git_branch: main
    ssh_key: deploy
```

Found by name, created or updated only when
something differs, check mode and `--diff`
included. `ssh_key` names a key; the module
looks up its id.

</td>
</tr>
</table>

## What every module does

- **Idempotent.** Objects are found by name. A module compares only the
  options you set and changes the server only when they differ.
- **Check mode and `--diff`** on every module, so you can see a change
  before making it.
- **Names, not ids.** Objects refer to each other by name (a template's
  `repository: ansible`, a robot's project), and the module resolves the ids.
- **Secrets handled on purpose.** Neither server returns a stored secret, so
  secrets follow `update_secret`: `always` sends the declared value on every
  run, `on_create` sends it only when the object is created. Secret options are
  never printed.
- **Safe deletes.** `state: absent` fails with a list of what still uses an
  object, instead of the server's own vague error. Deleting a whole project
  also needs `confirm_delete: true`.
- **API quirks handled.** Both APIs have update calls that quietly replace or
  drop fields. The modules send complete objects, so nothing you didn't mention
  gets lost. The quirks found along the way are listed in [PLAN.md](PLAN.md).
- **A matching `_info` module** for almost every module, returning objects in
  the shape the module takes.

## Quick start

**1. Install** straight from this repository (no Galaxy account needed) with
`requirements.yml`:

```yaml
collections:
  - name: https://github.com/ramanavelineni/ansible-collections.git#/ansible_collections/ramanavelineni/semaphoreui
    type: git
    version: semaphoreui-v0.2.1
  - name: https://github.com/ramanavelineni/ansible-collections.git#/ansible_collections/ramanavelineni/harbor
    type: git
    version: harbor-v0.2.0
```

```sh
ansible-galaxy collection install -r requirements.yml
```

**2. Describe what you want.** Set the connection once with
`module_defaults`, then list the objects.

<details open>
<summary><b>Semaphore UI</b>: a project with a key, repository, inventory, template and nightly schedule</summary>

```yaml
- hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.semaphoreui.semaphoreui:
      url: https://semaphore.example.com
      api_token: "{{ semaphore_api_token }}"
  tasks:
    - ramanavelineni.semaphoreui.project:
        name: homelab

    - ramanavelineni.semaphoreui.key_store:
        project: homelab
        name: deploy
        type: ssh
        ssh:
          login: git
          private_key: "{{ vault_deploy_key }}"
        update_secret: on_create

    - ramanavelineni.semaphoreui.repository:
        project: homelab
        name: ansible
        git_url: git@github.com:example/ansible.git
        git_branch: main
        ssh_key: deploy

    - ramanavelineni.semaphoreui.inventory:
        project: homelab
        name: homelab
        type: file
        inventory: inventories/homelab/hosts
        repository: ansible
        ssh_key: deploy

    - ramanavelineni.semaphoreui.variable_group:
        project: homelab
        name: default
        json: {}
        env: {}

    - ramanavelineni.semaphoreui.template:
        project: homelab
        name: site
        playbook: site.yml
        repository: ansible
        inventory: homelab
        variable_groups: [default]

    - ramanavelineni.semaphoreui.schedule:
        project: homelab
        name: nightly-site
        template: site
        cron: "0 3 * * *"
```

</details>

<details>
<summary><b>Harbor</b>: a scanned project with a quota, and a robot account that can push to it</summary>

```yaml
- hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.harbor.harbor:
      url: https://harbor.example.com
      username: admin
      password: "{{ harbor_admin_password }}"
  tasks:
    - ramanavelineni.harbor.project:
        name: apps
        metadata:
          auto_scan: true
          severity: high
          prevent_vul: true
        quota_gb: 50

    - ramanavelineni.harbor.robot_account:
        name: ci
        level: project
        project: apps
        permissions:
          - access:
              - {resource: repository, action: pull}
              - {resource: repository, action: push}
      register: ci_robot
      no_log: true   # a new robot's generated secret is in the result
```

</details>

**3. Run it** with `--check --diff` first to see what would change.

## Modules

<details>
<summary><b>ramanavelineni.semaphoreui</b>: 25 modules</summary>

| Area | Modules |
|---|---|
| Server | `info` |
| Projects | `project`, `project_info` |
| Key Store | `key_store`, `key_store_info` |
| Repositories | `repository`, `repository_info` |
| Inventories | `inventory`, `inventory_info` |
| Variable groups | `variable_group`, `variable_group_info` |
| Views (template tabs) | `view`, `view_info` |
| Task templates | `template`, `template_info` |
| Schedules and commit pollers | `schedule`, `schedule_info` |
| Integrations (inbound webhooks) | `integration`, `integration_info` |
| Team | `team_member`, `team_member_info` |
| Runners | `runner`, `runner_info` |
| Users | `user`, `user_info` |

Details: [collection README](ansible_collections/ramanavelineni/semaphoreui/)

</details>

<details>
<summary><b>ramanavelineni.harbor</b>: 23 modules</summary>

| Area | Modules |
|---|---|
| Server | `info` |
| Projects | `project`, `project_info` |
| Robot accounts | `robot_account`, `robot_account_info` |
| Registries (endpoints) | `registry`, `registry_info` |
| Replication rules | `replication`, `replication_info` |
| Webhooks | `webhook`, `webhook_info` |
| Tag retention | `tag_retention`, `tag_retention_info` |
| Tag immutability | `tag_immutability`, `tag_immutability_info` |
| Configuration (auth, OIDC, LDAP, …) | `configuration`, `configuration_info` |
| Garbage collection schedule | `garbage_collection`, `garbage_collection_info` |
| Vulnerability scan-all schedule | `scan_all`, `scan_all_info` |
| Audit log rotation | `log_rotation`, `log_rotation_info` |

Details: [collection README](ansible_collections/ramanavelineni/harbor/)

</details>

Every module's full documentation is available offline:
`ansible-doc ramanavelineni.semaphoreui.template`, `ansible-doc ramanavelineni.harbor.project`, and so on.

## Compatibility

| | Supported |
|---|---|
| ansible-core | 2.18, 2.19, 2.20, 2.21 |
| Semaphore UI | 2.18, 2.19 (Community; project runners need Pro) |
| Harbor | 2.14, 2.15 |
| Python | whatever your ansible-core supports |

Other server versions work but print a warning, because they haven't been
tested.

## How it's tested

Every change runs `ansible-test` sanity and unit tests on each supported
ansible-core version. The unit tests replay API responses recorded from real,
throwaway Semaphore and Harbor servers of every supported version. Each module
is also exercised live against those servers before it's merged.

## Development

```sh
make sanity                      # ansible-test sanity (semaphoreui by default)
make units COLLECTION=harbor     # unit tests for one collection
make changelog-lint              # check changelog fragments
make build                       # collection tarball into build/
```

- `ANSIBLE_TEST_FLAGS=--venv` runs the tests in virtual environments instead of
  containers.
- **Fixtures.** To re-record them from a throwaway server, for a new version
  or a new module, see the docstrings in `tools/record_semaphoreui_fixtures.py`
  and `tools/record_harbor_fixtures.py`.
- **Changelog.** Every user-facing change adds a changelog fragment under
  `ansible_collections/ramanavelineni/<collection>/changelogs/fragments/`.
- **Design.** Decisions, the order of work and every API quirk found are in
  [PLAN.md](PLAN.md).

## License

[Apache-2.0](LICENSE).
