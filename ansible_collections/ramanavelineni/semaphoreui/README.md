# ramanavelineni.semaphoreui

Declarative, idempotent Ansible modules for [Semaphore UI](https://semaphoreui.com):
one module per resource, looked up by name, changed only when it differs from
what you declare.

> **Status: in development.** Only the modules below exist so far; the
> rest are planned in [PLAN.md](../../../PLAN.md).

## Modules

| Module | Manages |
|---|---|
| `info` | server version, whether it is tested, registered apps (read-only) |
| `project` | projects (`state: present` / `absent`; deleting needs `confirm_delete: true`) |
| `project_info` | lists projects (read-only) |
| `key_store` | keys in a project's Key Store: `ssh`, `login_password`, `none` |
| `key_store_info` | lists a project's keys and the repositories using each (read-only) |
| `repository` | a project's repositories |
| `repository_info` | lists a project's repositories (read-only) |
| `inventory` | a project's inventories: `file`, `static`, `static-yaml` |
| `inventory_info` | lists a project's inventories (read-only) |
| `variable_group` | a project's variable groups: extra variables, environment variables, secrets |
| `variable_group_info` | lists a project's variable groups, with secret names but never values (read-only) |
| `view` | a project's views (template tabs): position, hidden, sort |
| `view_info` | lists a project's views (read-only) |
| `template` | task templates: app, repository, inventory, variable groups, view, vaults, survey variables, task parameters, build/deploy |

Every module looks objects up by name, changes only what differs from the
options you set, and supports check mode. Objects inside a project name it
with `project:`, and refer to each other by name too (a repository's
`ssh_key: github-deploy`).

Secrets can't be read back from Semaphore. `key_store` therefore sends a
declared secret on every run (`update_secret: always`, reported as changed),
or only when the key is created (`update_secret: on_create`). It never sends
the secret of a key a repository uses unless `force_repository_key_update: true`
is set: Semaphore deletes every checkout of those repositories on each update
of the key.

`variable_group` handles its secrets the same way (`update_secret`), leaves
secrets you don't list alone unless `purge_secrets: true`, and recreates a
secret whose type (`env` or `var`) changed, since Semaphore can't change it
in place.

`template` compares only the options you set and sends everything else back
unchanged, including fields it doesn't manage (such as 2.19's
`executor_image`). `task_params` is merged key by key, and a key the
template's app doesn't know fails instead of being ignored. The built-in
`All` view can be moved or hidden, but not deleted.

Deleting (`state: absent`) fails with a list of what still uses the object,
instead of Semaphore's own, misleading answer. `ansible-doc ramanavelineni.semaphoreui.<module>`
shows the full documentation.

## Connecting

Each module takes `url` and either `api_token` or `username` + `password`
(logged in and out within the task). Set them once for a play with the
collection's action group:

```yaml
- hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.semaphoreui.semaphoreui:
      url: https://semaphore.example.com
      api_token: "{{ semaphore_api_token }}"
      ca_path: /etc/ssl/certs/my-ca.pem   # optional: a private CA
  tasks:
    - ramanavelineni.semaphoreui.project:
        name: homelab
        max_parallel_tasks: 0
```

The same options can come from environment variables: `SEMAPHORE_URL`,
`SEMAPHORE_API_TOKEN`, `SEMAPHORE_USERNAME`, `SEMAPHORE_PASSWORD`,
`SEMAPHORE_VALIDATE_CERTS`, `SEMAPHORE_CA_PATH`.

## Requirements

- ansible-core 2.18 or newer
- Semaphore UI 2.18 or 2.19

## Installing

From Git (no Ansible Galaxy account needed), in `requirements.yml`:

```yaml
collections:
  - name: https://github.com/ramanavelineni/ansible-collections.git#/ansible_collections/ramanavelineni/semaphoreui
    type: git
    version: main   # use a semaphoreui-vX.Y.Z tag once one exists
```

```sh
ansible-galaxy collection install -r requirements.yml
```

## License

Apache-2.0. See [LICENSE](../../../LICENSE).
