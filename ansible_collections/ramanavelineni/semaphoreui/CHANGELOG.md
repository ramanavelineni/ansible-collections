# ramanavelineni\.semaphoreui Release Notes

**Topics**

- <a href="#v0-3-0">v0\.3\.0</a>
    - <a href="#release-summary">Release Summary</a>
    - <a href="#minor-changes">Minor Changes</a>
    - <a href="#bugfixes">Bugfixes</a>
- <a href="#v0-2-1">v0\.2\.1</a>
    - <a href="#release-summary-1">Release Summary</a>
    - <a href="#bugfixes-1">Bugfixes</a>
- <a href="#v0-2-0">v0\.2\.0</a>
    - <a href="#release-summary-2">Release Summary</a>
    - <a href="#breaking-changes--porting-guide">Breaking Changes / Porting Guide</a>
    - <a href="#security-fixes">Security Fixes</a>
    - <a href="#bugfixes-2">Bugfixes</a>
- <a href="#v0-1-0">v0\.1\.0</a>
    - <a href="#release-summary-3">Release Summary</a>
    - <a href="#new-modules">New Modules</a>

<a id="v0-3-0"></a>
## v0\.3\.0

<a id="release-summary"></a>
### Release Summary

New connection options \(<code>client\_cert</code>\, <code>client\_key</code>\, <code>use\_proxy</code>\)\, <code>project\_id</code> as an alternative to the project name\, custom apps in <code>template</code>\, and a round of bug fixes\. Some checks are stricter than in 0\.2\.1 and can make a task fail that ran before\: <code>template</code> refuses <code>start\_version</code> and <code>build\_template</code> on a template type that does not take them\, <code>schedule</code> refuses a <code>run\_at</code> without a time zone\, and negative <code>retries</code> or <code>retry\_delay</code> are refused\. Run with <code>\-\-check</code> once after upgrading\.

<a id="minor-changes"></a>
### Minor Changes

* all modules \- new connection option <code>use\_proxy</code> \(default <code>true</code>\, or <code>SEMAPHORE\_USE\_PROXY</code>\)\. <code>false</code> reaches the server directly even when <code>http\_proxy</code> or <code>https\_proxy</code> is set in the environment\. Until now the proxy from the environment was always used\.
* all modules \- new connection options <code>client\_cert</code> and <code>client\_key</code> present a TLS client certificate to a server that asks for one \(mutual TLS\)\. They can also come from <code>SEMAPHORE\_CLIENT\_CERT</code> and <code>SEMAPHORE\_CLIENT\_KEY</code>\. A path that is not a file\, and a <code>client\_key</code> without a <code>client\_cert</code>\, fail before a request is sent\.
* integration\, inventory\, key\_store\, repository\, runner\, schedule\, team\_member\, template\, variable\_group\, view and their <code>\_info</code> modules \- new option <code>project\_id</code> names the project by its id instead of by name with <code>project</code>\. The list of projects is not read then\, only that one project\, so these modules work on a server with 200 or more projects\, where Semaphore cuts the list off and a lookup by name is refused\. <code>project</code> and <code>project\_id</code> exclude each other\.
* integration\, inventory\, key\_store\, repository\, schedule\, team\_member\, template\, variable\_group\, view and their <code>\_info</code> modules \- a task that names no project now fails with <code>one of the following is required\: project\, project\_id</code> instead of <code>missing required arguments\: project</code>\.
* key\_store\, schedule\, team\_member \- the rules between options that the argument spec can express are now part of it\: <code>type</code> and <code>role</code> are required with <code>state\=present</code>\, and <code>cron</code> and <code>run\_at</code> exclude each other\. A task that breaks one fails during argument validation\, before the module logs in\, with Ansible\'s own wording \(<code>state is present but all of the following are missing\: type</code>\, <code>parameters are mutually exclusive\: cron\|run\_at</code>\) instead of the module\'s\.

<a id="bugfixes"></a>
### Bugfixes

* all modules \- <code>SEMAPHORE\_API\_TOKEN</code> in the environment no longer makes a task that sets <code>username</code> and <code>password</code> fail with \"parameters are mutually exclusive\"\, and <code>SEMAPHORE\_USERNAME</code> or <code>SEMAPHORE\_PASSWORD</code> no longer does that to a task that sets <code>api\_token</code>\. What the task sets wins\; the environment is read only for what the task leaves out\. With nothing set in the task and both kinds in the environment\, the token is used\, where this failed before\.
* all modules \- <code>timeout</code> below 1 and a negative <code>retries</code> or <code>retry\_delay</code> fail before any request\. <code>timeout\: 0</code> used to fail with \"Operation now in progress\"\, and negative <code>retries</code> and <code>retry\_delay</code> were silently read as 0\.
* all modules \- a <code>url</code> that does not start with <code>http\://</code> or <code>https\://</code> fails before any request with a message showing the expected form\, instead of <code>unknown url type</code>\.
* all modules \- a failure message quotes at most 500 characters of the server\'s answer and says how much it left out\. A proxy\'s error page used to make the message thousands of characters long\. The whole answer is still returned in <code>request\_details\.response</code>\.
* all modules \- when the server answers with a redirect\, the message names the address it points to and says to set <code>url</code> to the address the server answers on\. The address is also returned as <code>request\_details\.location</code>\. Redirects are still not followed\.
* inventory\, integration\, template\, variable\_group \- with <code>state\=absent</code> the diff\'s <code>before</code> is the whole object\, in the shape an update shows\, instead of only <code>id</code> and <code>name</code>\. The other modules already did this\.
* repository \- with <code>state\=absent</code> the diff\'s <code>before</code> has the name of the SSH key in <code>ssh\_key</code> instead of <code>null</code>\.
* runner \- check mode with <code>regenerate\_token\: true</code> on a registered runner now returns <code>registered\: false</code> in <code>runner</code> and in the diff\, as the real run does\.
* runner \- the request for a registration token is repeated on a transient failure\, like the read requests \(see <code>retries</code>\)\. It was sent once\, so a gateway error right after the create left a runner without a token while the task failed\, and the next run found the runner and returned no token\.
* runner \- when the token of a new runner still cannot be fetched\, the module deletes the runner again and says so\, so the next run starts over\. If the delete fails too\, the message points to <code>regenerate\_token\: true</code>\.
* schedule \- <code>run\_at</code> is sent to Semaphore in UTC \(<code>2026\-10\-01T03\:00\:00Z</code>\) instead of exactly as typed\, so a value YAML read as a timestamp no longer goes out with a space in place of the <code>T</code>\. A value that is not a date and time\, or names no time zone\, now fails before anything is changed\, with an example of an accepted value\.
* schedule \- the template lists are no longer read when the project\'s schedule list already has the schedule of that name\, which saves one request per template on every such task\. They are still read for a commit poller and for a schedule that does not exist yet\.
* schedule\, schedule\_info \- a schedule that both the project list and a template list return is counted once\. It used to fail with \"More than one schedule is named\"\.
* template \- <code>app</code> no longer has a fixed list of choices\, so a template can use an app an administrator registered on the Semaphore server\. Such an app is checked against the server\'s app list \(a warning instead of a failure in check mode\)\, and its <code>task\_params</code> are sent without checking the keys\. The apps Semaphore ships with behave as before\.
* template \- <code>arguments</code> the task did not change go back as stored\. A stored value that is not a JSON list\, such as <code>\-v \-\-diff</code>\, was rewritten as <code>\[\"\-v \-\-diff\"\]</code> by any other change\.
* template \- <code>start\_version</code> on a template that is not of type <code>build</code>\, and <code>build\_template</code> on one that is not of type <code>deploy</code>\, now fail with a message naming the option and the type\. Semaphore does not store them for other types\, so the task reported a change on every run while nothing was written\. An empty value is still accepted for every type\.
* template \- a template or survey variable whose type this module does not know no longer makes every update fail with a <code>KeyError</code>\.
* template \- after an update that changes <code>type</code>\, the returned template no longer shows a <code>start\_version</code> or <code>build\_template</code> that the new type does not keep\.
* template \- an update no longer rewrites the survey variables the task did not change\. They go back to the server as stored\, so fields this module has no option for\, such as the <code>target</code> of Semaphore 2\.19\, are kept\. When the task does change <code>survey\_vars</code>\, a variable that keeps its name keeps those fields too\.
* variable\_group \- a stored <code>json</code> or <code>env</code> value that is not valid JSON no longer blocks the task that replaces it\, nor the deletion of the group\. The diff shows the stored text as <code>before</code>\. A task that leaves the broken field alone still fails\, as an update would write it back\.

<a id="v0-2-1"></a>
## v0\.2\.1

<a id="release-summary-1"></a>
### Release Summary

Check mode now works for a play that builds a project from nothing\.

<a id="bugfixes-1"></a>
### Bugfixes

* integration\, inventory\, key\_store\, repository\, runner\, schedule\, team\_member\, template\, variable\_group\, view \- check mode no longer fails when the project\, or another object the task refers to by name\, does not exist yet\. An earlier task of the same run may create it\, so the task is reported as changed with a warning and an empty result\. Outside check mode it fails as before\. This makes <code>\-\-check</code> usable for a play that builds a project from nothing\.

<a id="v0-2-0"></a>
## v0\.2\.0

<a id="release-summary-2"></a>
### Release Summary

A security release\. A failed request no longer shows secrets\, and the collection now includes its <code>LICENSE</code>\. Also several fixes to the client and the <code>\_info</code> modules\. Two results changed form\, see the breaking changes\.

<a id="breaking-changes--porting-guide"></a>
### Breaking Changes / Porting Guide

* All modules \- <code>request\_details\.request</code> in a failed result is now a dictionary\, not a JSON string\.
* inventory\_info\, project\_info\, repository\_info \- fields of the raw API answer that the matching module does not return \(such as a project\'s <code>created</code>\) are no longer returned\.

<a id="security-fixes"></a>
### Security Fixes

* All modules \- a failed request no longer shows secrets\. The request body in <code>request\_details</code> was returned as JSON text\, where a secret containing a newline\, a quote\, a backslash or a non\-ASCII character is escaped and so was not masked\: every SSH private key of <code>key\_store</code>\, and such values of <code>variable\_group</code> secrets\, <code>user\_password</code> and the login <code>password</code>\. The body is now returned as a dictionary with secret values replaced by <code>\*\*\*\*\*\*\*\*</code>\.

<a id="bugfixes-2"></a>
### Bugfixes

* Add the <code>LICENSE</code> file to the collection\, so that installs and release tarballs include the license text\.
* All modules \- an unexpected error \(a server that answers in an unexpected form\, a port that doesn\'t speak HTTP\) now fails with a message instead of a Python traceback\, and the login session is always closed\.
* integration\, inventory\, key\_store\, repository\, runner\, schedule\, team\_member\, template\, variable\_group\, view \- <code>state\=absent</code> now reports no change when the project doesn\'t exist\, instead of failing\.
* inventory\_info\, project\_info\, repository\_info\, user\_info \- return each object in the same form as the matching module\, with every field filled in\. <code>project\_info</code> left out <code>alert</code>\, <code>alert\_chat</code> and <code>max\_parallel\_tasks</code> when they had their default value\.
* template \- the survey variable type <code>text</code> is now refused on every Semaphore older than 2\.19\, not only on 2\.18\.
* user \- an HTTP 500 on delete is only explained as the pre\-2\.19 session problem when the server is older than 2\.19\.

<a id="v0-1-0"></a>
## v0\.1\.0

<a id="release-summary-3"></a>
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
