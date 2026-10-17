# ramanavelineni\.semaphoreui Release Notes

**Topics**

- <a href="#v0-5-1">v0\.5\.1</a>
    - <a href="#release-summary">Release Summary</a>
    - <a href="#bugfixes">Bugfixes</a>
- <a href="#v0-5-0">v0\.5\.0</a>
    - <a href="#release-summary-1">Release Summary</a>
    - <a href="#minor-changes">Minor Changes</a>
    - <a href="#security-fixes">Security Fixes</a>
    - <a href="#bugfixes-1">Bugfixes</a>
- <a href="#v0-4-0">v0\.4\.0</a>
    - <a href="#release-summary-2">Release Summary</a>
    - <a href="#security-fixes-1">Security Fixes</a>
    - <a href="#bugfixes-2">Bugfixes</a>
    - <a href="#new-plugins">New Plugins</a>
        - <a href="#filter">Filter</a>
    - <a href="#new-modules">New Modules</a>
    - <a href="#new-roles">New Roles</a>
- <a href="#v0-3-1">v0\.3\.1</a>
    - <a href="#release-summary-3">Release Summary</a>
    - <a href="#bugfixes-3">Bugfixes</a>
    - <a href="#known-issues">Known Issues</a>
- <a href="#v0-3-0">v0\.3\.0</a>
    - <a href="#release-summary-4">Release Summary</a>
    - <a href="#minor-changes-1">Minor Changes</a>
    - <a href="#bugfixes-4">Bugfixes</a>
- <a href="#v0-2-1">v0\.2\.1</a>
    - <a href="#release-summary-5">Release Summary</a>
    - <a href="#bugfixes-5">Bugfixes</a>
- <a href="#v0-2-0">v0\.2\.0</a>
    - <a href="#release-summary-6">Release Summary</a>
    - <a href="#breaking-changes--porting-guide">Breaking Changes / Porting Guide</a>
    - <a href="#security-fixes-2">Security Fixes</a>
    - <a href="#bugfixes-6">Bugfixes</a>
- <a href="#v0-1-0">v0\.1\.0</a>
    - <a href="#release-summary-7">Release Summary</a>
    - <a href="#new-modules-1">New Modules</a>

<a id="v0-5-1"></a>
## v0\.5\.1

<a id="release-summary"></a>
### Release Summary

A task the module waited for now always comes back with its end time\, and the fields Semaphore stores as JSON in a string are read with one rule in every module\.

<a id="bugfixes"></a>
### Bugfixes

* task \- a task the module waited for could come back with an empty <code>end</code>\. Semaphore saves a task\'s final status a moment before its end time\, and the module stopped reading at the status\. It now reads the task again\, at most four times half a second apart\, until the end time is there\.
* task\, task\_info\, template\, template\_info\, variable\_group\, variable\_group\_info \- the fields Semaphore stores as JSON in a string \(a task\'s <code>arguments</code> and <code>variables</code>\, a template\'s <code>arguments</code>\, a variable group\'s <code>json</code> and <code>env</code>\) are now read with one rule\. Valid JSON is returned parsed\, and any other text is returned as Semaphore stores it\. Before\, a template wrapped such text in a list\, a task returned valid JSON of an unexpected kind as text\, and variable\_group\_info failed on a group with broken JSON\. An unset field is still an empty list or dict\. The return documentation now says so\.
* template \- <code>arguments</code> stored as anything other than a JSON list\, for example plain text that Semaphore refuses to run\, no longer counts as equal to the list given\. The module writes the list once\, and the next run reports no change\.

<a id="v0-5-0"></a>
## v0\.5\.0

<a id="release-summary-1"></a>
### Release Summary

Exported projects apply again without changes\, projects past the first 200 can be reached by id\, the roles no longer print webhook URLs or registration tokens with \-v\, and the modules gain secret survey variables\, settled run\_at schedules and a shared transport that stops at once on certificate errors\.

<a id="minor-changes"></a>
### Minor Changes

* project \- new option <code>id</code>\. The module reads only that project\, not the list of projects that Semaphore cuts off at 200\, and renames it when its name differs from <code>name</code>\. A missing id fails with <code>state\=present</code> and is no change with <code>state\=absent</code>\.
* project\_apply role \- a project file may set <code>id\:</code>\. The project is then read by its id and renamed to <code>name</code> when that differs\. Every entry of a project now names it by the id the project task returned\, so a project with an id is found on a server with more than 200 projects\.
* project\_info \- new option <code>id</code>\. It reads only that project and returns it\, or an empty list when it does not exist or the user cannot see it\.

<a id="security-fixes"></a>
### Security Fixes

* project\_apply\, server\_apply \- with <code>project\_apply\_no\_log</code> or <code>server\_apply\_no\_log</code> on\, a run with <code>\-v</code> printed the skipped items of the tasks that show new webhook URLs and registration tokens\, the URLs and tokens included\. These tasks now loop over nothing when no\_log is on\.

<a id="bugfixes-1"></a>
### Bugfixes

* project\_apply role \- two files or directories that declare the same project <code>name</code> now fail before anything changes\, and the message names both\. Before\, both were applied to the one project\, one after the other\.
* project\_export role \- <code>project\_export\_overwrite</code> no longer replaces the vault file\. The role writes the vault file only when it does not exist yet\, so values filled in by hand stay\.
* project\_export role \- <code>project\_export\_project\_id</code> reads that one project instead of looking for it in the list of projects\, which Semaphore cuts off at 200\. A project is now found by id on any server\.
* project\_export role \- a file that has the same content and another mode\, such as <code>0600</code>\, no longer counts as a difference that stops the role\. Such a file is not written again and keeps its mode\.
* project\_export role \- every key and variable group with a secret is written with <code>update\_secret\: on\_create</code>\. Applying an exported project again no longer sends its secrets and reports a change every run\. To push a changed vault value\, set <code>update\_secret\: always</code> on that entry\.
* project\_restore \- when Semaphore refuses the name because of a project the user can\'t see\, the message no longer says that a re\-run will work\. It says to restore under another name or as an administrator\. The documentation says that only projects the user can see are found\.
* schedule \- a past <code>run\_at</code> for a schedule that is missing or inactive reports no change with a warning\, instead of failing with HTTP 400 on every run after a one\-time schedule ran\. A past <code>run\_at</code> on an active schedule fails before anything is sent\.
* semaphoreui modules \- a certificate that does not verify\, a <code>ca\_path</code> that does not exist and a host name that does not resolve now fail at the first request\. Before\, a read was sent again up to <code>retries</code> times\, <code>retry\_delay</code> seconds apart\, although asking again cannot fix a setting\. A refused connection\, a timeout and a busy name resolver are still retried\.
* semaphoreui modules \- a pre\-release version such as <code>v2\.19\-rc1</code> now counts as the tested release 2\.19\. Before\, the modules warned that it was untested\, while the checks for what a server version supports already read it as 2\.19\.
* task \- refuse <code>task\_params\.skip\_galaxy\_install</code> when the template does not set <code>allow\_override\_skip\_galaxy\_install</code> and the value differs from the template\'s own\, because Semaphore ignores it then\.
* template \- accept <code>secret</code> as a survey variable type\, which Semaphore 2\.18 and 2\.19 offer and the task module\'s <code>secret\_variables</code> fill\. Before\, declaring the survey variables deleted a secret variable made in the UI\, or turned it into a plain one\. A <code>secret</code> variable takes no <code>default\_value</code>\.

<a id="v0-4-0"></a>
## v0\.4\.0

<a id="release-summary-2"></a>
### Release Summary

New roles that apply whole projects and servers from YAML descriptions and export a project as one\, six new modules for tasks\, project backups\, API tokens and the event log\, and fixes that keep runner tokens\, webhook URLs and echoed secrets out of task output\.

<a id="security-fixes-1"></a>
### Security Fixes

* a failed request now masks every <code>no\_log</code> value of the task in what the server answered\, as written and in the escaped forms JSON from Python and from Go use\. Before\, only the API token and the password were masked there\, so a server that repeated a private key or a secret in an error showed it\.
* project\_apply \- the webhook URLs of every integration were printed on every run\, and the integrations task was not covered by <code>project\_apply\_no\_log</code>\. The task is now hidden by <code>project\_apply\_no\_log</code>\, and only the URLs of integrations created in the run are shown\, and only with <code>project\_apply\_no\_log\=false</code>\.
* project\_backup \- the returned <code>backup</code> and the diff showed each project runner\'s auth token and every integration alias \(the secret part of a webhook URL\)\. They are now shown as <code>\*\*\*\*\*\*\*\*</code>\. The file written at <code>dest</code> still holds them\, and the module documentation no longer says a backup holds no secrets\.
* server\_apply \- the runners task\, whose result holds a new runner\'s registration token\, was not covered by <code>server\_apply\_no\_log</code>\, and new tokens were always printed\. Both now follow <code>server\_apply\_no\_log</code>\.

<a id="bugfixes-2"></a>
### Bugfixes

* runner\, user\_token \- the examples used a string as a <code>when</code> condition\, which ansible\-core 2\.19 and later refuse \(<code>Conditional result was derived from value of type \'str\'</code>\)\. They now test <code>\| length \> 0</code>\.

<a id="new-plugins"></a>
### New Plugins

<a id="filter"></a>
#### Filter

* ramanavelineni\.semaphoreui\.project\_export\_config \- Turn what the Semaphore \_info modules return into a project configuration\.
* ramanavelineni\.semaphoreui\.project\_export\_vault \- Write the list of vault variables an exported Semaphore project needs\.
* ramanavelineni\.semaphoreui\.project\_export\_vault\_variables \- List the vault variables an exported Semaphore project needs\.
* ramanavelineni\.semaphoreui\.project\_export\_yaml \- Write a Semaphore project as the YAML file the project\_apply role reads\.

<a id="new-modules"></a>
### New Modules

* ramanavelineni\.semaphoreui\.event\_info \- Read the activity log of Semaphore UI\.
* ramanavelineni\.semaphoreui\.project\_backup \- Read a Semaphore UI project\'s backup\, and write it to a file\.
* ramanavelineni\.semaphoreui\.project\_restore \- Create a Semaphore UI project from a backup\.
* ramanavelineni\.semaphoreui\.task \- Run a Semaphore UI template\, or stop a task\.
* ramanavelineni\.semaphoreui\.task\_info \- Read Semaphore UI tasks and their output\.
* ramanavelineni\.semaphoreui\.user\_token \- Manage the API tokens of the user that logs in\.

<a id="new-roles"></a>
### New Roles

* ramanavelineni\.semaphoreui\.project\_apply \- Apply a directory of project descriptions to Semaphore UI\.
* ramanavelineni\.semaphoreui\.project\_export \- Write a Semaphore project as the YAML configuration the project\_apply role reads\.
* ramanavelineni\.semaphoreui\.server\_apply \- Apply users and runners to a Semaphore UI server\.

<a id="v0-3-1"></a>
## v0\.3\.1

<a id="release-summary-3"></a>
### Release Summary

Bug fixes found by running the modules against real servers\. One of them changes what a task does on some servers\: <code>integration</code> now fails when a task drops a matcher or an extracted value and the server keeps it\, where it used to report a change on every run\. See the known issue below for the servers this applies to\.

<a id="bugfixes-3"></a>
### Bugfixes

* all modules \- a token or password taken from <code>SEMAPHORE\_API\_TOKEN</code> or <code>SEMAPHORE\_PASSWORD</code> that the server repeats in an error is now taken out of the failure message and of <code>request\_details\.response</code> by the client itself\. Until now this relied on ansible\-core masking the result\, which the development version of ansible\-core \(2\.23\.0\.dev0\) no longer does for values a module registers at run time\. No released ansible\-core version from 2\.18 to 2\.21 showed such a value\.
* integration \- a matcher or an extracted value the task no longer lists is deleted first\, and the lists are read again before anything else is changed\. When the server answered the deletion with success but kept the entry\, the task now fails and says so\. Before\, it reported a change on every run and returned the integration without the entry\. In check mode the task warns that it cannot tell\.
* template \- creating a template in check mode returned <code>name\: null</code> in <code>template</code> and in the diff\. It now returns the name\, as a real run does\.

<a id="known-issues"></a>
### Known Issues

* integration \- Semaphore 2\.18 and 2\.19 with an SQLite database do not remove a matcher or an extracted value through the API\; they answer the request with success and keep the entry\. To drop one on such a server\, remove the integration with <code>state\: absent</code> and create it again\. It gets a new webhook URL then\.

<a id="v0-3-0"></a>
## v0\.3\.0

<a id="release-summary-4"></a>
### Release Summary

New connection options \(<code>client\_cert</code>\, <code>client\_key</code>\, <code>use\_proxy</code>\)\, <code>project\_id</code> as an alternative to the project name\, custom apps in <code>template</code>\, and a round of bug fixes\. Some checks are stricter than in 0\.2\.1 and can make a task fail that ran before\: <code>template</code> refuses <code>start\_version</code> and <code>build\_template</code> on a template type that does not take them\, <code>schedule</code> refuses a <code>run\_at</code> without a time zone\, and negative <code>retries</code> or <code>retry\_delay</code> are refused\. Run with <code>\-\-check</code> once after upgrading\.

<a id="minor-changes-1"></a>
### Minor Changes

* all modules \- new connection option <code>use\_proxy</code> \(default <code>true</code>\, or <code>SEMAPHORE\_USE\_PROXY</code>\)\. <code>false</code> reaches the server directly even when <code>http\_proxy</code> or <code>https\_proxy</code> is set in the environment\. Until now the proxy from the environment was always used\.
* all modules \- new connection options <code>client\_cert</code> and <code>client\_key</code> present a TLS client certificate to a server that asks for one \(mutual TLS\)\. They can also come from <code>SEMAPHORE\_CLIENT\_CERT</code> and <code>SEMAPHORE\_CLIENT\_KEY</code>\. A path that is not a file\, and a <code>client\_key</code> without a <code>client\_cert</code>\, fail before a request is sent\.
* integration\, inventory\, key\_store\, repository\, runner\, schedule\, team\_member\, template\, variable\_group\, view and their <code>\_info</code> modules \- new option <code>project\_id</code> names the project by its id instead of by name with <code>project</code>\. The list of projects is not read then\, only that one project\, so these modules work on a server with 200 or more projects\, where Semaphore cuts the list off and a lookup by name is refused\. <code>project</code> and <code>project\_id</code> exclude each other\.
* integration\, inventory\, key\_store\, repository\, schedule\, team\_member\, template\, variable\_group\, view and their <code>\_info</code> modules \- a task that names no project now fails with <code>one of the following is required\: project\, project\_id</code> instead of <code>missing required arguments\: project</code>\.
* key\_store\, schedule\, team\_member \- the rules between options that the argument spec can express are now part of it\: <code>type</code> and <code>role</code> are required with <code>state\=present</code>\, and <code>cron</code> and <code>run\_at</code> exclude each other\. A task that breaks one fails during argument validation\, before the module logs in\, with Ansible\'s own wording \(<code>state is present but all of the following are missing\: type</code>\, <code>parameters are mutually exclusive\: cron\|run\_at</code>\) instead of the module\'s\.

<a id="bugfixes-4"></a>
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

<a id="release-summary-5"></a>
### Release Summary

Check mode now works for a play that builds a project from nothing\.

<a id="bugfixes-5"></a>
### Bugfixes

* integration\, inventory\, key\_store\, repository\, runner\, schedule\, team\_member\, template\, variable\_group\, view \- check mode no longer fails when the project\, or another object the task refers to by name\, does not exist yet\. An earlier task of the same run may create it\, so the task is reported as changed with a warning and an empty result\. Outside check mode it fails as before\. This makes <code>\-\-check</code> usable for a play that builds a project from nothing\.

<a id="v0-2-0"></a>
## v0\.2\.0

<a id="release-summary-6"></a>
### Release Summary

A security release\. A failed request no longer shows secrets\, and the collection now includes its <code>LICENSE</code>\. Also several fixes to the client and the <code>\_info</code> modules\. Two results changed form\, see the breaking changes\.

<a id="breaking-changes--porting-guide"></a>
### Breaking Changes / Porting Guide

* All modules \- <code>request\_details\.request</code> in a failed result is now a dictionary\, not a JSON string\.
* inventory\_info\, project\_info\, repository\_info \- fields of the raw API answer that the matching module does not return \(such as a project\'s <code>created</code>\) are no longer returned\.

<a id="security-fixes-2"></a>
### Security Fixes

* All modules \- a failed request no longer shows secrets\. The request body in <code>request\_details</code> was returned as JSON text\, where a secret containing a newline\, a quote\, a backslash or a non\-ASCII character is escaped and so was not masked\: every SSH private key of <code>key\_store</code>\, and such values of <code>variable\_group</code> secrets\, <code>user\_password</code> and the login <code>password</code>\. The body is now returned as a dictionary with secret values replaced by <code>\*\*\*\*\*\*\*\*</code>\.

<a id="bugfixes-6"></a>
### Bugfixes

* Add the <code>LICENSE</code> file to the collection\, so that installs and release tarballs include the license text\.
* All modules \- an unexpected error \(a server that answers in an unexpected form\, a port that doesn\'t speak HTTP\) now fails with a message instead of a Python traceback\, and the login session is always closed\.
* integration\, inventory\, key\_store\, repository\, runner\, schedule\, team\_member\, template\, variable\_group\, view \- <code>state\=absent</code> now reports no change when the project doesn\'t exist\, instead of failing\.
* inventory\_info\, project\_info\, repository\_info\, user\_info \- return each object in the same form as the matching module\, with every field filled in\. <code>project\_info</code> left out <code>alert</code>\, <code>alert\_chat</code> and <code>max\_parallel\_tasks</code> when they had their default value\.
* template \- the survey variable type <code>text</code> is now refused on every Semaphore older than 2\.19\, not only on 2\.18\.
* user \- an HTTP 500 on delete is only explained as the pre\-2\.19 session problem when the server is older than 2\.19\.

<a id="v0-1-0"></a>
## v0\.1\.0

<a id="release-summary-7"></a>
### Release Summary

First release\. 25 modules that manage Semaphore UI 2\.18 and 2\.19 declaratively\: projects\, the Key Store\, repositories\, inventories\, variable groups\, views\, task templates\, schedules and commit pollers\, integrations\, team members\, runners and users\, each with an <code>\_info</code> module\. Objects are found and referenced by name\, only the options you set are compared\, and every module supports check mode and diff\.

<a id="new-modules-1"></a>
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
