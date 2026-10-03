# Security policy

## Reporting a vulnerability

Please don't open a public issue for a security problem. Report it privately:
on the repository's **Security** tab, choose **Report a vulnerability**
([direct link](https://github.com/ramanavelineni/ansible-collections/security/advisories/new)).

Useful in a report: the collection and version, the module, the server
version (Semaphore UI or Harbor), and a task that shows the problem. Leave
real secrets out; a made-up value in the same place is enough.

This is a one-person project, so there is no response time to promise. You
will get an answer in the advisory thread, and a fix is released with a
`security_fixes` changelog entry that credits you unless you'd rather not be
named.

## What counts

- A module or a failure message showing a secret (a password, token, key or
  auth header) in task output, logs or diffs.
- A module sending credentials somewhere other than the configured server, or
  skipping TLS verification when it wasn't asked to.
- A secret in a committed test fixture.

A vulnerability in Semaphore UI or Harbor themselves belongs to those
projects.

## Supported versions

Only the latest release of each collection gets fixes.
