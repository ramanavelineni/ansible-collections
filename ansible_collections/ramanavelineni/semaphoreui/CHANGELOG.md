# ramanavelineni\.semaphoreui Release Notes

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

A security release\. A failed request no longer shows secrets\, and the collection now includes its <code>LICENSE</code>\. Also several fixes to the client and the <code>\_info</code> modules\. Two results changed form\, see the breaking changes\.

<a id="breaking-changes--porting-guide"></a>
### Breaking Changes / Porting Guide

* All modules \- <code>request\_details\.request</code> in a failed result is now a dictionary\, not a JSON string\.
* inventory\_info\, project\_info\, repository\_info \- fields of the raw API answer that the matching module does not return \(such as a project\'s <code>created</code>\) are no longer returned\.

<a id="security-fixes"></a>
### Security Fixes

* All modules \- a failed request no longer shows secrets\. The request body in <code>request\_details</code> was returned as JSON text\, where a secret containing a newline\, a quote\, a backslash or a non\-ASCII character is escaped and so was not masked\: every SSH private key of <code>key\_store</code>\, and such values of <code>variable\_group</code> secrets\, <code>user\_password</code> and the login <code>password</code>\. The body is now returned as a dictionary with secret values replaced by <code>\*\*\*\*\*\*\*\*</code>\.

<a id="bugfixes"></a>
### Bugfixes

* Add the <code>LICENSE</code> file to the collection\, so that installs and release tarballs include the license text\.
* All modules \- an unexpected error \(a server that answers in an unexpected form\, a port that doesn\'t speak HTTP\) now fails with a message instead of a Python traceback\, and the login session is always closed\.
* integration\, inventory\, key\_store\, repository\, runner\, schedule\, team\_member\, template\, variable\_group\, view \- <code>state\=absent</code> now reports no change when the project doesn\'t exist\, instead of failing\.
* inventory\_info\, project\_info\, repository\_info\, user\_info \- return each object in the same form as the matching module\, with every field filled in\. <code>project\_info</code> left out <code>alert</code>\, <code>alert\_chat</code> and <code>max\_parallel\_tasks</code> when they had their default value\.
* template \- the survey variable type <code>text</code> is now refused on every Semaphore older than 2\.19\, not only on 2\.18\.
* user \- an HTTP 500 on delete is only explained as the pre\-2\.19 session problem when the server is older than 2\.19\.

<a id="v0-1-0"></a>
## v0\.1\.0

<a id="release-summary-1"></a>
### Release Summary

First release\. 25 modules that manage Semaphore UI 2\.18 and 2\.19 declaratively\: projects\, the Key Store\, repositories\, inventories\, variable groups\, views\, task templates\, schedules and commit pollers\, integrations\, team members\, runners and users\, each with an <code>\_info</code> module\. Objects are found and referenced by name\, only the options you set are compared\, and every module supports check mode and diff\.

<a id="new-modules"></a>
### New Modules

* ramanavelineni\.semaphoreui\.info \- Read Semaphore UI server information and registered apps\.
* ramanavelineni\.semaphoreui\.integration \- Manage integrations \(inbound webhooks\) in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.integration\_info \- List the integrations \(inbound webhooks\) in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.inventory \- Manage inventories in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.inventory\_info \- List the inventories in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.key\_store \- Manage keys in a Semaphore UI project\'s Key Store\.
* ramanavelineni\.semaphoreui\.key\_store\_info \- List the keys in a Semaphore UI project\'s Key Store\.
* ramanavelineni\.semaphoreui\.project \- Manage Semaphore UI projects\.
* ramanavelineni\.semaphoreui\.project\_info \- List Semaphore UI projects\.
* ramanavelineni\.semaphoreui\.repository \- Manage repositories in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.repository\_info \- List the repositories in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.runner \- Manage Semaphore UI runners\.
* ramanavelineni\.semaphoreui\.runner\_info \- List Semaphore UI runners\.
* ramanavelineni\.semaphoreui\.schedule \- Manage schedules in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.schedule\_info \- List the schedules in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.team\_member \- Manage who belongs to a Semaphore UI project\, and with which role\.
* ramanavelineni\.semaphoreui\.team\_member\_info \- List the team of a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.template \- Manage task templates in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.template\_info \- List the task templates in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.user \- Manage Semaphore UI users\.
* ramanavelineni\.semaphoreui\.user\_info \- List Semaphore UI users\.
* ramanavelineni\.semaphoreui\.variable\_group \- Manage variable groups in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.variable\_group\_info \- List the variable groups in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.view \- Manage views \(template tabs\) in a Semaphore UI project\.
* ramanavelineni\.semaphoreui\.view\_info \- List the views \(template tabs\) in a Semaphore UI project\.
