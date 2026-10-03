# Local test and build targets. ansible-test only runs from inside the
# collection directory, so every target cds there first.
#
#   make sanity                      # ansible-test sanity in a container
#   make units                       # unit tests in a container
#   make coverage                    # unit tests with coverage, against the floor
#   make lint                        # ansible-lint and the sanity ignore files
#   make docs-lint                   # antsibull-docs lint of the module docs
#   make install-test                # build, install elsewhere, use from there
#   make live                        # live suite against a real server (see below)
#   make changelog-lint              # check changelog fragments
#   make tools-test                  # tests for the fixture recorders in tools/
#   make build                       # collection tarball into build/
#   make sanity COLLECTION=harbor    # the other collection
#
# ansible-test runs its container through docker, or through podman when
# docker isn't installed. ANSIBLE_TEST_FLAGS=--venv runs without containers.
#
# make live runs tests/live of the collection against a server you name in the
# environment (SEMAPHORE_URL, SEMAPHORE_USERNAME, SEMAPHORE_PASSWORD, or
# HARBOR_URL, HARBOR_USERNAME, HARBOR_PASSWORD). Without the URL the tests are
# skipped. Throwaway servers only: the tests create and delete objects.

NAMESPACE          ?= ramanavelineni
COLLECTION         ?= semaphoreui
COLLECTION_DIR     := ansible_collections/$(NAMESPACE)/$(COLLECTION)
ANSIBLE_TEST       ?= ansible-test
ANSIBLE_TEST_FLAGS ?= --docker
ANTSIBULL_CHANGELOG ?= antsibull-changelog
ANTSIBULL_DOCS     ?= antsibull-docs
ANSIBLE_LINT       ?= ansible-lint
PYTEST             ?= python3 -m pytest
BUILD_DIR          := $(CURDIR)/build

.PHONY: help sanity units coverage lint docs-lint install-test live tools-test changelog-lint changelog build clean

help:
	@sed -n 's/^#   //p' $(firstword $(MAKEFILE_LIST))

sanity:
	cd $(COLLECTION_DIR) && $(ANSIBLE_TEST) sanity $(ANSIBLE_TEST_FLAGS) -v --color

units:
	cd $(COLLECTION_DIR) && $(ANSIBLE_TEST) units $(ANSIBLE_TEST_FLAGS) -v --color

# The floor is in the script; CI runs the same two commands.
coverage:
	cd $(COLLECTION_DIR) && $(ANSIBLE_TEST) units $(ANSIBLE_TEST_FLAGS) --coverage
	cd $(COLLECTION_DIR) && $(CURDIR)/.github/scripts/coverage-floor.sh $(COLLECTION) $(ANSIBLE_TEST_FLAGS)

lint:
	cd $(COLLECTION_DIR) && $(ANSIBLE_LINT)
	.github/scripts/check-sanity-ignore.py $(COLLECTION)

# The repository root has ansible_collections/ in it, so it is a collections path.
docs-lint:
	ANSIBLE_COLLECTIONS_PATH=$(CURDIR) $(ANTSIBULL_DOCS) lint-collection-docs --plugin-docs \
		--validate-collection-refs self --disallow-unknown-collection-refs $(COLLECTION_DIR)

install-test:
	.github/scripts/install-test.sh $(COLLECTION)

# Never run in CI: it needs a real server. The connection comes from the
# environment, see the top of this file.
live:
	PYTHONPATH=$(CURDIR) $(PYTEST) $(COLLECTION_DIR)/tests/live -v

# The recorders are not part of a collection, so ansible-test doesn't see them.
tools-test:
	python3 -B -m unittest discover -s tools/tests -v

changelog-lint:
	cd $(COLLECTION_DIR) && $(ANTSIBULL_CHANGELOG) lint

# Turns the fragments into CHANGELOG.md for the version in galaxy.yml.
# Run when cutting a release, never on a feature branch.
changelog:
	cd $(COLLECTION_DIR) && $(ANTSIBULL_CHANGELOG) release

build:
	mkdir -p $(BUILD_DIR)
	ansible-galaxy collection build $(COLLECTION_DIR) --output-path $(BUILD_DIR) --force

clean:
	rm -rf $(BUILD_DIR) $(COLLECTION_DIR)/tests/output
