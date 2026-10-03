# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Shared helpers for the configuration and configuration_info modules."""

import re

# Every writable setting of /configurations (identical in Harbor 2.14 and
# 2.15), secrets excepted, with its type.
SETTING_TYPES = dict(
    audit_log_forward_endpoint=str, auth_mode=str, banner_message=str, disabled_audit_log_event_types=str,
    http_authproxy_admin_groups=str, http_authproxy_admin_usernames=str, http_authproxy_endpoint=str,
    http_authproxy_server_certificate=str, http_authproxy_skip_search=bool,
    http_authproxy_tokenreview_endpoint=str, http_authproxy_verify_cert=bool, ldap_base_dn=str,
    ldap_filter=str, ldap_group_admin_dn=str, ldap_group_attach_parallel=bool, ldap_group_attribute_name=str,
    ldap_group_base_dn=str, ldap_group_membership_attribute=str, ldap_group_search_filter=str,
    ldap_group_search_scope=int, ldap_scope=int, ldap_search_dn=str, ldap_timeout=int, ldap_uid=str,
    ldap_url=str, ldap_verify_cert=bool, notification_enable=bool, oidc_admin_group=str,
    oidc_auto_onboard=bool, oidc_client_id=str, oidc_endpoint=str, oidc_extra_redirect_parms=str,
    oidc_group_filter=str, oidc_groups_claim=str, oidc_logout=bool, oidc_name=str, oidc_scope=str,
    oidc_user_claim=str, oidc_verify_cert=bool, primary_auth_mode=bool, project_creation_restriction=str,
    quota_per_project_enable=bool, read_only=bool, robot_name_prefix=str, robot_token_duration=int,
    scanner_skip_update_pulltime=bool, self_registration=bool, session_timeout=int,
    skip_audit_log_database=bool, storage_per_project=int, token_expiration=int, uaa_client_id=str,
    uaa_endpoint=str, uaa_verify_cert=bool,
)
# Secrets Harbor never returns, and the setting each belongs to.
WRITE_ONLY = dict(oidc_client_secret='oidc_client_id', ldap_search_password='ldap_search_dn')
# Returned by Harbor, but a secret: compared, never output.
READABLE_SECRETS = ('uaa_client_secret',)
# A key Harbor returns that is not in SETTING_TYPES and has one of these words
# in its name is taken for a secret a newer Harbor added, and left out as well.
# Settings above that have such a word (robot_token_duration, token_expiration,
# http_authproxy_tokenreview_endpoint) are known not to be secrets and stay.
SECRET_NAME = re.compile(r'secret|password|passwd|token|credential|private_key', re.IGNORECASE)


def is_secret(key):
    """Whether the value of this /configurations key must stay out of the output."""
    if key in READABLE_SECRETS or key in WRITE_ONLY:
        return True
    return key not in SETTING_TYPES and bool(SECRET_NAME.search(key))


def flat(configurations):
    """{key: value} of GET /configurations ({key: {value, editable}}), secrets left out."""
    out = {}
    for key, item in (configurations or {}).items():
        if is_secret(key):
            continue
        out[key] = item.get('value') if isinstance(item, dict) else item
    return out


def locked(configurations, keys):
    """Those of `keys` that Harbor marks as not editable, sorted."""
    out = []
    for key in keys:
        item = (configurations or {}).get(key)
        if isinstance(item, dict) and item.get('editable') is False:
            out.append(key)
    return sorted(out)
