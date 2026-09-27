# ansible-collections

Ansible collections that manage services declaratively through their APIs,
so roles call one idempotent module per resource instead of writing REST
calls with `ansible.builtin.uri`.

| Collection | Manages | Status |
|---|---|---|
| [`ramanavelineni.semaphoreui`](ansible_collections/ramanavelineni/semaphoreui/) | Semaphore UI | in development: `info`, `project`, `key_store`, `repository`, `inventory`, `variable_group`, `view`, `template`, `schedule`, `integration`, `team_member`, `runner`, `user` (+ `_info` modules) |
| [`ramanavelineni.harbor`](ansible_collections/ramanavelineni/harbor/) | Harbor | in development: `info`, `project`, `project_info` |

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

Unit tests run the modules against responses recorded from real servers,
stored under `tests/unit/plugins/fixtures/<major.minor>/<area>.json` in each
collection. To re-record them (for a new tested version, or a new module),
start a throwaway server of that version and run the recorder; see the
docstrings in `tools/record_semaphoreui_fixtures.py` and
`tools/record_harbor_fixtures.py`. Both record one area at a time, so areas
can be recorded separately.

Every change that affects users adds a changelog fragment under
`ansible_collections/ramanavelineni/<collection>/changelogs/fragments/`.

`pre-commit install` enables the light hooks (whitespace, YAML, changelog
lint); the full checks run in CI on every pull request.

## License

Apache-2.0. See [LICENSE](LICENSE).
