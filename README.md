# ansible-collections

Ansible collections that manage services declaratively through their APIs,
so roles call one idempotent module per resource instead of writing REST
calls with `ansible.builtin.uri`.

| Collection | Manages | Status |
|---|---|---|
| [`ramanavelineni.semaphoreui`](ansible_collections/ramanavelineni/semaphoreui/) | Semaphore UI | in development, no modules yet |
| `ramanavelineni.harbor` | Harbor | planned |

The design, the module lists and the order of work are in [PLAN.md](PLAN.md).

## Installing

Collections install straight from this repository with Git; see each
collection's README for the `requirements.yml` entry. Publishing to Ansible
Galaxy may come later.

## Development

Needs ansible-core 2.18 or newer, `antsibull-changelog`, and docker or
podman for the test containers.

```sh
make sanity            # ansible-test sanity
make units             # unit tests
make changelog-lint    # check changelog fragments
make build             # collection tarball into build/
make sanity COLLECTION=harbor   # target another collection
```

`ANSIBLE_TEST_FLAGS=--venv` runs the tests in virtual environments instead of
containers.

Every change that affects users adds a changelog fragment under
`ansible_collections/ramanavelineni/<collection>/changelogs/fragments/`.

`pre-commit install` enables the light hooks (whitespace, YAML, changelog
lint); the full checks run in CI on every pull request.

## License

Apache-2.0. See [LICENSE](LICENSE).
