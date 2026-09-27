# ramanavelineni.semaphoreui

Declarative, idempotent Ansible modules for [Semaphore UI](https://semaphoreui.com):
one module per resource, looked up by name, changed only when it differs from
what you declare.

> **Status: not usable yet.** This collection has no modules so far. The
> design and the order of work are in [PLAN.md](../../../PLAN.md).

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
