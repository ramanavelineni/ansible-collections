# ramanavelineni\.semaphoreui Release Notes

**Topics**

- <a href="#v0-1-0">v0\.1\.0</a>
    - <a href="#release-summary">Release Summary</a>
    - <a href="#new-modules">New Modules</a>

<a id="v0-1-0"></a>
## v0\.1\.0

<a id="release-summary"></a>
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
