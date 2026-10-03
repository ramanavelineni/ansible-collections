# Local test and build targets. ansible-test only runs from inside the
# collection directory, so every target cds there first.
#
#   make sanity                      # ansible-test sanity in a container
#   make units                       # unit tests in a container
#   make changelog-lint              # check changelog fragments
#   make tools-test                  # tests for the fixture recorders in tools/
#   make build                       # collection tarball into build/
#   make sanity COLLECTION=harbor    # another collection (once it exists)
#
# ansible-test runs its container through docker, or through podman when
# docker isn't installed. ANSIBLE_TEST_FLAGS=--venv runs without containers.

NAMESPACE          ?= ramanavelineni
COLLECTION         ?= semaphoreui
COLLECTION_DIR     := ansible_collections/$(NAMESPACE)/$(COLLECTION)
ANSIBLE_TEST       ?= ansible-test
ANSIBLE_TEST_FLAGS ?= --docker
ANTSIBULL_CHANGELOG ?= antsibull-changelog
BUILD_DIR          := $(CURDIR)/build

.PHONY: help sanity units tools-test changelog-lint changelog build clean

help:
	@sed -n 's/^#   //p' $(firstword $(MAKEFILE_LIST))

sanity:
	cd $(COLLECTION_DIR) && $(ANSIBLE_TEST) sanity $(ANSIBLE_TEST_FLAGS) -v --color

units:
	cd $(COLLECTION_DIR) && $(ANSIBLE_TEST) units $(ANSIBLE_TEST_FLAGS) -v --color

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
