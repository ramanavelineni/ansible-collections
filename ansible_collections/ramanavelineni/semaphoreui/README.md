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

Every module looks objects up by name, changes only what differs from the
options you set, and supports check mode. `ansible-doc ramanavelineni.semaphoreui.<module>`
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
