# Contributing

Bug reports, fixes and new modules are welcome. For anything larger than a
fix, open an issue first, so the options and behaviour can be agreed before
the code is written. Security problems go through [SECURITY.md](SECURITY.md),
not through an issue.

[PLAN.md](PLAN.md) holds the design decisions, the conventions every module
follows, and each API quirk found so far. Read "Conventions for every module"
before changing a module.

## Running the tests

`ansible-test` only works from inside a collection directory; the Makefile
goes there for you. `COLLECTION` is `semaphoreui` (the default) or `harbor`.

```sh
make sanity COLLECTION=harbor    # ansible-test sanity
make units COLLECTION=harbor     # unit tests
make changelog-lint              # check changelog fragments
make tools-test                  # tests for the fixture recorders
make build                       # collection tarball into build/
```

The first two run in a container (docker, or podman when docker isn't
installed). `ANSIBLE_TEST_FLAGS="--venv --python 3.13"` runs them in a virtual
environment instead.

CI runs sanity and the unit tests for both collections on ansible-core 2.18,
2.19, 2.20 and 2.21, and lints the changelog fragments. A pull request that
only changes Markdown skips CI.

## What a change needs

- **Tests.** Unit tests replay recorded API responses (see Fixtures below).
  A new behaviour gets a test; a bug fix gets a test that fails without it.
- **A changelog fragment** for every change a user can notice: a YAML file
  under `ansible_collections/ramanavelineni/<collection>/changelogs/fragments/`
  with one of the sections of `changelogs/config.yaml` (`bugfixes`,
  `minor_changes`, `breaking_changes`, `security_fixes`, ...). New modules
  need none; they are listed from their `version_added`. Don't edit
  `CHANGELOG.md` or `changelogs/changelog.yaml`; they are generated at
  release time.
- **Documentation.** Module docs live in the module's `DOCUMENTATION`,
  `EXAMPLES` and `RETURN`. A new module is also added to its collection's
  README and to `meta/runtime.yml`'s action group.
- **One ignore line per module.** `validate-modules` expects a GPL header,
  which these Apache-2.0 modules don't have. A new module needs this line in
  every `tests/sanity/ignore-2.*.txt` of its collection, and nothing else
  goes into those files:

  ```
  plugins/modules/<name>.py validate-modules:missing-gplv3-license # Apache-2.0 collection, see LICENSE
  ```

## No GPL code

The collections are Apache-2.0. Most of ansible-core is GPL-3.0, so:

- import only ansible-core's BSD-licensed `module_utils` and the Python
  standard library;
- don't extend ansible-core's doc fragments and don't use its test helpers;
- don't copy code from ansible-core or from GPL-licensed collections, other
  Semaphore and Harbor collections included.

By opening a pull request you agree that your contribution is licensed under
Apache-2.0, like the rest of the repository.

## Fixtures

The unit tests replay responses recorded from real servers, one file per
area and server version, under `tests/unit/plugins/fixtures/`. When a module
needs a response that isn't there, record it; don't write it by hand.

```sh
SEMAPHORE_PASSWORD=<password> tools/record_semaphoreui_fixtures.py http://127.0.0.1:3019 [AREA ...]
HARBOR_PASSWORD=<password> tools/record_harbor_fixtures.py http://127.0.0.1:8015 [AREA ...]
```

Each script's docstring says how to start a server and what an area must do.
The rules:

- **Throwaway servers only.** The recorders create, change and delete
  objects, and what the server answers is committed to a public repository.
  They refuse a server that isn't on a loopback address unless
  `--allow-remote` is passed; pass it only for another throwaway.
- **Own objects only.** An area creates what it needs under its own names,
  deletes it again, and filters every listing down to those objects with
  `keep()`.
- **No secrets.** A value the server generates (a robot secret, a runner
  token) is replaced by a placeholder before it is stored. The recorder
  refuses to write a file in which it finds the admin password, a generated
  secret or something shaped like a credential. Read the diff of a new
  recording anyway before committing it.
- Record every supported server version, not only the newest.

## Commits and pull requests

- One topic per pull request, against `main`.
- Titles follow [Conventional Commits](https://www.conventionalcommits.org/):
  `fix(harbor): ...`, `feat(semaphoreui): ...`, `docs: ...`, `chore: ...`.
  Pull requests are squashed, so the title becomes the commit.
- `pre-commit install` sets up the light local checks from
  `.pre-commit-config.yaml`.

## Releases

Maintainers only. Each collection is versioned on its own
([semantic versioning](https://semver.org/)). A release pull request sets the
version in `galaxy.yml` and runs `make changelog COLLECTION=<collection>`.
Once it is merged, pushing the tag `<collection>-v<version>` on `main` makes
the release workflow build the tarball and publish the GitHub Release.
