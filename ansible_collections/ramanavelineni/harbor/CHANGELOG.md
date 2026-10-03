# ramanavelineni\.harbor Release Notes

**Topics**

- <a href="#v0-3-0">v0\.3\.0</a>
    - <a href="#release-summary">Release Summary</a>
    - <a href="#minor-changes">Minor Changes</a>
    - <a href="#security-fixes">Security Fixes</a>
    - <a href="#bugfixes">Bugfixes</a>
- <a href="#v0-2-0">v0\.2\.0</a>
    - <a href="#release-summary-1">Release Summary</a>
    - <a href="#breaking-changes--porting-guide">Breaking Changes / Porting Guide</a>
    - <a href="#security-fixes-1">Security Fixes</a>
    - <a href="#bugfixes-1">Bugfixes</a>
- <a href="#v0-1-0">v0\.1\.0</a>
    - <a href="#release-summary-2">Release Summary</a>
    - <a href="#new-modules">New Modules</a>

<a id="v0-3-0"></a>
## v0\.3\.0

<a id="release-summary"></a>
### Release Summary

New connection options \(<code>client\_cert</code>\, <code>client\_key</code>\, <code>use\_proxy</code>\, <code>warn\_untested\_version</code>\)\, modules that work for users who are not administrators\, and a round of bug fixes\. Some checks are stricter than in 0\.2\.0 and can make a task fail that ran before\: <code>configuration</code> refuses to change a setting Harbor reports as not editable\, <code>registry</code> takes only <code>basic</code> or <code>oauth</code> as <code>credential\_type</code>\, and negative <code>retries</code> or <code>retry\_delay</code> are refused\. Run with <code>\-\-check</code> once after upgrading\.

<a id="minor-changes"></a>
### Minor Changes

* all modules \- new connection option <code>use\_proxy</code> \(default <code>true</code>\, or <code>HARBOR\_USE\_PROXY</code>\)\. <code>false</code> reaches the server directly even when <code>http\_proxy</code> or <code>https\_proxy</code> is set in the environment\. Until now the proxy from the environment was always used\.
* all modules \- new connection option <code>warn\_untested\_version</code> \(environment variable <code>HARBOR\_WARN\_UNTESTED\_VERSION</code>\)\. Set it to <code>false</code> to stop the warning that every task prints on a Harbor version the collection is not tested with\. The default\, <code>true</code>\, keeps the warning\.
* all modules \- new connection options <code>client\_cert</code> and <code>client\_key</code> present a TLS client certificate to a server that asks for one \(mutual TLS\)\. They can also come from <code>HARBOR\_CLIENT\_CERT</code> and <code>HARBOR\_CLIENT\_KEY</code>\. A path that is not a file\, and a <code>client\_key</code> without a <code>client\_cert</code>\, fail before a request is sent\.
* registry \- <code>credential\_type</code> now takes <code>basic</code> or <code>oauth</code> only\, and anything else fails before a request is sent\.
* robot\_account \- <code>level</code> <code>project</code> without <code>project</code> is now refused by the argument check\, before the login\, with <code>level is project but all of the following are missing\: project</code>\.

<a id="security-fixes"></a>
### Security Fixes

* configuration\, configuration\_info \- a key that Harbor returns and these modules have no name for is left out of <code>configuration</code> when its name contains <code>secret</code>\, <code>password</code>\, <code>passwd</code>\, <code>token</code>\, <code>credential</code> or <code>private\_key</code>\. The secrets were recognised by a fixed list of names\, so a readable secret added by a newer Harbor would have been returned in clear text\. No Harbor version tested so far returns such a key\.

<a id="bugfixes"></a>
### Bugfixes

* all modules \- <code>timeout</code> below 1 and a negative <code>retries</code> or <code>retry\_delay</code> fail before a request is sent\. <code>timeout\: 0</code> used to fail with \"Operation now in progress\"\, and a negative <code>retries</code> or <code>retry\_delay</code> was silently read as 0\.
* all modules \- a <code>url</code> without <code>http\://</code> or <code>https\://</code>\, with another scheme or without a host fails before a request is sent\, with a message showing the expected form\. It used to fail with urllib\'s <code>unknown url type</code> and no hint\.
* all modules \- a failure that asking again cannot cure is no longer retried\: a certificate that does not verify\, a <code>ca\_path</code> file that does not exist and a host name that does not resolve now fail at once instead of after <code>retries</code> times <code>retry\_delay</code> seconds\. A refused or reset connection and a timeout are retried as before\.
* all modules \- a list endpoint that ignores the page number and answers with the same full page each time is now read once instead of for ever\, and a list that still has not ended after 1000 pages fails the task\.
* all modules \- a list is read to its end when a server or proxy answers with pages shorter than the 100 items asked for\: the <code>X\-Total\-Count</code> header now decides when it is present\. Before\, the first short page ended the list\, so objects past it were not seen\.
* all modules \- a redirect \(HTTP 301\, 302\, 307\, 308\) is reported with the address it points to and a hint to set <code>url</code> to the address the Harbor server itself answers on\. The target is also returned as <code>request\_details\.location</code>\. Redirects are still not followed\.
* all modules \- an answer that is cut short or is not HTTP at all is now reported\, and for reads retried\, like any other connection failure\, instead of ending in a Python traceback\.
* all modules \- an answer the module does not expect\, such as a create answered with an empty body or without a <code>Location</code> header\, now fails the task with a message that starts with <code>Unexpected</code> and names the error\, instead of a Python traceback\. The traceback is still shown with <code>\-vvv</code>\.
* configuration \- <code>settings</code> values that arrive as strings after templating are accepted\: a string of digits for an integer setting\, and <code>true</code>\, <code>false</code>\, <code>yes</code>\, <code>no</code>\, <code>on</code> or <code>off</code> for a boolean one\.
* configuration \- changing a setting that Harbor reports as not editable\, such as <code>auth\_mode</code> once a second user exists\, now fails before anything is sent\, with the names of those settings\. A declared value that is already in place is still not a change\.
* garbage\_collection \- <code>delete\_tag</code> on a server whose version cannot be read is now sent\, and Harbor decides\, as <code>project</code> and <code>registry</code> already did for their options that need Harbor 2\.15\. Before\, the task failed with \"delete\_tag needs Harbor 2\.15 or newer\"\.
* garbage\_collection\, log\_rotation \- a change no longer drops the schedule settings the module has no option for\. Harbor replaces a schedule\'s settings as a whole\, so a garbage collection schedule created through the API with <code>dry\_run</code> lost it\, and became a real garbage collection\, on any change made by the module\.
* garbage\_collection\, log\_rotation \- a schedule of a type other than <code>none</code>\, <code>hourly</code>\, <code>daily</code>\, <code>weekly</code> or <code>custom</code> no longer ends in a <code>KeyError</code> when a task changes only its settings\. The task fails with a message that names the type and says to set <code>schedule</code>\. The <code>\_info</code> modules return such a schedule with its type as Harbor reports it\, in lower case\.
* garbage\_collection\_info\, log\_rotation\_info \- <code>runs</code> above 100 no longer returns only 100 runs\. Harbor returns at most 100 per request\, so more than that are now read in several requests\.
* project \- a project is no longer taken for missing on the word of an anonymous answer\. Harbor answers anonymously for a moment after another client failed to log in as the same user\, and its project list then leaves out private projects without saying so\. <code>state\: absent</code> reported no change for a private project that exists\, and <code>state\: present</code> tried to create it and failed with HTTP 409\. The login is now checked again before a project that is not in the list is treated as missing\, and the list is read again when Harbor was in such a lock\. A project that is found costs no request more\.
* project\, project\_info \- a user who is not a Harbor administrator can now use them\. Registries are read only for <code>proxy\_registry</code> and proxy\-cache projects\, and a quota or registry the user may not read \(HTTP 401 or 403\) is returned as <code>null</code>\. Setting <code>quota\_gb</code> or <code>proxy\_registry</code> as such a user fails with an explanation\.
* project\, registry\, replication\, webhook\, tag\_retention \- the object an update returns\, and the <code>after</code> of its diff\, are now read back from Harbor after the write instead of being worked out from the options\. They show what Harbor stored\: a <code>registry</code> update returns the <code>status</code> of the check Harbor makes on that write\, where it returned the status from before\. <code>tag\_retention</code> reads the policy back after a create too\. Each update costs one read more\, and a <code>project</code> update that sets <code>quota\_gb</code> two\.
* project\, registry\, replication\, webhook\, tag\_retention \- when Harbor stored a value differently from what the task sent\, the task now warns and names the fields\, because the next run will find the difference and report a change again\. Before\, the result showed the value the task sent\.
* project\_info \- the list of projects is no longer returned without its private projects while Harbor answers anonymously\. The login is checked again after the list is read\, which is one more request for each task that does not name a project that exists\.
* registry \- an <code>access\_key</code> set on an endpoint that has no credential type yet is now sent with <code>credential\_type</code> <code>basic</code> \(or the declared one\)\. It was sent with an empty type before\, unless <code>access\_secret</code> was sent too\.
* replication \- a <code>tag</code> or <code>label</code> filter without a <code>decoration</code> and one with <code>matches</code> are the same filter and no longer compare as different\, which rewrote the rule once\. Such a filter is now sent and returned with <code>decoration</code> <code>matches</code>\.
* robot\_account \- in check mode\, creating a robot account with a declared <code>secret</code> now reports <code>secret\_updated</code> as <code>true</code>\, as the real run does\.
* robot\_account \- when a new robot account\'s declared <code>secret</code> cannot be set\, the robot account is deleted again and the task fails\, instead of leaving a robot whose secret nobody knows\.
* robot\_account\, robot\_account\_info\, webhook\, webhook\_info\, tag\_retention\, tag\_retention\_info\, tag\_immutability\, tag\_immutability\_info \- \"Project does not exist\" is no longer reported for a private project that Harbor left out of an anonymous answer\. When Harbor stays anonymous\, or is in a lock every time the project is looked up\, the task fails and says that\, instead of acting on what it was shown\.
* tag\_retention \- a create answered without a <code>Location</code> header now finds the new policy through the project and returns its <code>id</code>\, where <code>id</code> was null\.
* tag\_retention\, tag\_retention\_info\, tag\_immutability\, tag\_immutability\_info \- the project is looked up by name \(<code>GET /projects\?name\=</code>\) as the other modules do\, instead of reading every project\.
* webhook \- <code>event\_types</code> no longer has a fixed list of choices\, so an event a newer Harbor adds can be used\. An event other than the ten of Harbor 2\.14 and 2\.15 is checked against the events the server offers for the project\. One the server does not offer fails with <code>Unknown event types</code>\, or is a warning in check mode\.

<a id="v0-2-0"></a>
## v0\.2\.0

<a id="release-summary-1"></a>
### Release Summary

A security release\. A failed request no longer shows secrets\, and the collection now includes its <code>LICENSE</code>\. Also fixes to <code>project</code> quotas and robot account lookups\. One result changed form\, see the breaking changes\.

<a id="breaking-changes--porting-guide"></a>
### Breaking Changes / Porting Guide

* All modules \- <code>request\_details\.request</code> in a failed result is now a dictionary\, not a JSON string\.

<a id="security-fixes-1"></a>
### Security Fixes

* All modules \- a failed request no longer shows secrets\. The request body in <code>request\_details</code> was returned as JSON text\, where a secret containing a quote\, a backslash or a non\-ASCII character is escaped and so was not masked\: such values of <code>robot\_account</code> <code>secret</code>\, <code>registry</code> <code>access\_secret</code>\, <code>configuration</code> <code>oidc\_client\_secret</code> and <code>ldap\_search\_password</code>\. The body is now returned as a dictionary with secret values replaced by <code>\*\*\*\*\*\*\*\*</code>\.
* webhook \- a failed update no longer shows the webhook\'s stored auth header\, which the update sends back to Harbor\.

<a id="bugfixes-1"></a>
### Bugfixes

* Add the <code>LICENSE</code> file to the collection\, so that installs and release tarballs include the license text\.
* project \- <code>quota\_gb</code> on a project that has no quota in Harbor now fails with an explanation\, instead of being ignored and reported as unchanged\.
* robot\_account\, robot\_account\_info \- a failed read of Harbor\'s robot name prefix is now reported\. Only a user who may not read the configuration \(HTTP 401 or 403\) falls back to the default prefix\.

<a id="v0-1-0"></a>
## v0\.1\.0

<a id="release-summary-2"></a>
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
