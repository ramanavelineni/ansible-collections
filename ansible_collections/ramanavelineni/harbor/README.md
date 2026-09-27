# ramanavelineni.harbor

Declarative, idempotent Ansible modules for [Harbor](https://goharbor.io):
one module per resource, looked up by name, changed only when it differs from
what you declare.

> **Status: in development.** Only the modules below exist so far; the
> rest are planned in [PLAN.md](../../../PLAN.md).

## Modules

| Module | Manages |
|---|---|
| `info` | server version and whether it is tested (read-only) |
| `project` | projects: visibility, metadata, proxy-cache registry, storage quota (`state: absent` needs `confirm_delete: true`) |
| `project_info` | lists projects (read-only) |
| `robot_account` | system and project robot accounts: permissions (compared in any order), duration, description, secret |
| `robot_account_info` | lists system or project robot accounts, never secrets (read-only) |
| `registry` | registry endpoints (Administration > Registries): type, URL, credentials, CA certificate (2.15) |
| `registry_info` | lists registry endpoints, never secrets (read-only) |
| `replication` | replication rules (Administration > Replications): pull or push, trigger, filters |
| `replication_info` | lists replication rules (read-only) |
| `webhook` | a project's webhooks: events, endpoint, auth header, payload format |
| `webhook_info` | lists a project's webhooks, without their auth headers (read-only) |

Every module looks objects up by name, changes only what differs from the
options you set, and supports check mode. `ansible-doc ramanavelineni.harbor.<module>`
shows the full documentation.

`project` checks metadata keys and values before sending them: Harbor itself
silently drops unknown keys and stores an invalid severity as `unknown`.

`registry` sends a declared `access_secret` on every run (`update_secret: always`)
or only when the endpoint is created (`on_create`); Harbor never returns it.
Harbor checks that an endpoint is reachable whenever it is created or changed.
An endpoint's type can't be changed, so a different type fails with
instructions. `replication` compares filters regardless of their order and
checks cron expressions and filters before sending anything.

## Connecting

Harbor's API only takes HTTP basic authentication. Each module takes `url`,
`username` and `password`: an administrator, an ordinary user, a robot
account (`robot$name` and its secret) or an OIDC user with their CLI secret.
Harbor answers some requests anonymously when the credentials are wrong
instead of refusing them, so every module first checks that the login was
accepted.

Set the connection once for a play with the collection's action group:

```yaml
- hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.harbor.harbor:
      url: https://harbor.example.com
      username: admin
      password: "{{ harbor_admin_password }}"
      ca_path: /etc/ssl/certs/my-ca.pem   # optional: a private CA
  tasks:
    - ramanavelineni.harbor.project:
        name: apps
        metadata:
          auto_scan: true
        quota_gb: 50
```

The same options can come from environment variables: `HARBOR_URL`,
`HARBOR_USERNAME`, `HARBOR_PASSWORD`, `HARBOR_VALIDATE_CERTS`,
`HARBOR_CA_PATH`.

## Requirements

- ansible-core 2.18 or newer
- Harbor 2.14 or 2.15

## Installing

From Git (no Ansible Galaxy account needed), in `requirements.yml`:

```yaml
collections:
  - name: https://github.com/ramanavelineni/ansible-collections.git#/ansible_collections/ramanavelineni/harbor
    type: git
    version: main   # use a harbor-vX.Y.Z tag once one exists
```

```sh
ansible-galaxy collection install -r requirements.yml
```

## License

Apache-2.0. See [LICENSE](../../../LICENSE).
