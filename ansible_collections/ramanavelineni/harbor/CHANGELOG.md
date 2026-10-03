# ramanavelineni\.harbor Release Notes

**Topics**

- <a href="#v0-2-0">v0\.2\.0</a>
    - <a href="#release-summary">Release Summary</a>
    - <a href="#breaking-changes--porting-guide">Breaking Changes / Porting Guide</a>
    - <a href="#security-fixes">Security Fixes</a>
    - <a href="#bugfixes">Bugfixes</a>
- <a href="#v0-1-0">v0\.1\.0</a>
    - <a href="#release-summary-1">Release Summary</a>
    - <a href="#new-modules">New Modules</a>

<a id="v0-2-0"></a>
## v0\.2\.0

<a id="release-summary"></a>
### Release Summary

A security release\. A failed request no longer shows secrets\, and the collection now includes its <code>LICENSE</code>\. Also fixes to <code>project</code> quotas and robot account lookups\. One result changed form\, see the breaking changes\.

<a id="breaking-changes--porting-guide"></a>
### Breaking Changes / Porting Guide

* All modules \- <code>request\_details\.request</code> in a failed result is now a dictionary\, not a JSON string\.

<a id="security-fixes"></a>
### Security Fixes

* All modules \- a failed request no longer shows secrets\. The request body in <code>request\_details</code> was returned as JSON text\, where a secret containing a quote\, a backslash or a non\-ASCII character is escaped and so was not masked\: such values of <code>robot\_account</code> <code>secret</code>\, <code>registry</code> <code>access\_secret</code>\, <code>configuration</code> <code>oidc\_client\_secret</code> and <code>ldap\_search\_password</code>\. The body is now returned as a dictionary with secret values replaced by <code>\*\*\*\*\*\*\*\*</code>\.
* webhook \- a failed update no longer shows the webhook\'s stored auth header\, which the update sends back to Harbor\.

<a id="bugfixes"></a>
### Bugfixes

* Add the <code>LICENSE</code> file to the collection\, so that installs and release tarballs include the license text\.
* project \- <code>quota\_gb</code> on a project that has no quota in Harbor now fails with an explanation\, instead of being ignored and reported as unchanged\.
* robot\_account\, robot\_account\_info \- a failed read of Harbor\'s robot name prefix is now reported\. Only a user who may not read the configuration \(HTTP 401 or 403\) falls back to the default prefix\.

<a id="v0-1-0"></a>
## v0\.1\.0

<a id="release-summary-1"></a>
### Release Summary

First release\. 23 modules that manage Harbor 2\.14 and 2\.15 declaratively\: projects\, robot accounts\, registries\, replication rules\, webhooks\, tag retention and immutability\, system configuration\, and the garbage collection\, scan\-all and audit\-log rotation schedules\, each with an <code>\_info</code> module\. Objects are found and referenced by name\, only the options you set are compared\, and every module supports check mode and diff\.

<a id="new-modules"></a>
### New Modules

* ramanavelineni\.harbor\.configuration \- Manage Harbor\'s system configuration\.
* ramanavelineni\.harbor\.configuration\_info \- Read Harbor\'s system configuration\.
* ramanavelineni\.harbor\.garbage\_collection \- Manage Harbor\'s garbage collection schedule\.
* ramanavelineni\.harbor\.garbage\_collection\_info \- Read Harbor\'s garbage collection schedule and recent runs\.
* ramanavelineni\.harbor\.info \- Read Harbor server information\.
* ramanavelineni\.harbor\.log\_rotation \- Manage Harbor\'s audit log rotation schedule\.
* ramanavelineni\.harbor\.log\_rotation\_info \- Read Harbor\'s audit log rotation schedule and recent purges\.
* ramanavelineni\.harbor\.project \- Manage Harbor projects\.
* ramanavelineni\.harbor\.project\_info \- List Harbor projects\.
* ramanavelineni\.harbor\.registry \- Manage Harbor registry endpoints\.
* ramanavelineni\.harbor\.registry\_info \- List Harbor registry endpoints\.
* ramanavelineni\.harbor\.replication \- Manage Harbor replication rules\.
* ramanavelineni\.harbor\.replication\_info \- List Harbor replication rules\.
* ramanavelineni\.harbor\.robot\_account \- Manage Harbor robot accounts\.
* ramanavelineni\.harbor\.robot\_account\_info \- List Harbor robot accounts\.
* ramanavelineni\.harbor\.scan\_all \- Manage Harbor\'s scheduled vulnerability scan of all artifacts\.
* ramanavelineni\.harbor\.scan\_all\_info \- Read Harbor\'s Scan All schedule and latest scan metrics\.
* ramanavelineni\.harbor\.tag\_immutability \- Manage a tag immutability rule of a Harbor project\.
* ramanavelineni\.harbor\.tag\_immutability\_info \- List the tag immutability rules of a Harbor project\.
* ramanavelineni\.harbor\.tag\_retention \- Manage a Harbor project\'s tag retention policy\.
* ramanavelineni\.harbor\.tag\_retention\_info \- Read a Harbor project\'s tag retention policy\.
* ramanavelineni\.harbor\.webhook \- Manage webhooks of a Harbor project\.
* ramanavelineni\.harbor\.webhook\_info \- List the webhooks of a Harbor project\.
