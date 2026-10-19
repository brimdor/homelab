# Private service DNS on OPNSense

`network/configs/dnsmasq-private-hosts.json` owns exactly three Dnsmasq DNS host
overrides: `git.eaglepass.io`, `registry.eaglepass.io`, and `auth.eaglepass.io`, all
pointing to the ingress controller at `10.0.20.226`. Update this desired state if
ingress ownership changes. Public DNS currently publishes this private address;
these internal answers preserve Git SSH on port 22 without Cloudflare proxying.

The October 18, 2026 read-only inspection found OPNSense `25.7.9_7`, Dnsmasq on
TCP/UDP port 53, and Unbound stopped despite its saved enabled flag. Unbound's
`registry.eaglepass.io` exception does not affect Dnsmasq. Do not start Unbound,
change node resolvers, disable global rebinding protection, or restore the stale
whole `network/configs/opnsense-config.xml` snapshot to implement this correction.

## Reviewed contract

OPNsense's package revision counts commits after the release tag. The seventh
linear commit after `25.7.9` is
`c6ffd18ec3f1c07651fe917093e0a53c342b9e24` (`25.7.9_7`). Sources:

- [Dnsmasq model 1.0.8](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/mvc/app/models/OPNsense/Dnsmasq/Dnsmasq.xml)
- [Host API controller](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/mvc/app/controllers/OPNsense/Dnsmasq/Api/SettingsController.php)
- [Dnsmasq template](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/service/templates/OPNsense/Dnsmasq/dnsmasq.conf)
- [Service controller](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/mvc/app/controllers/OPNsense/Dnsmasq/Api/ServiceController.php), [base controller](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/mvc/app/controllers/OPNsense/Base/ApiMutableServiceControllerBase.php), and [backend](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/etc/inc/plugins.inc.d/dnsmasq.inc)
- [Current full configuration download](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/www/diag_backup.php)

The running `GET /api/dnsmasq/settings/get_host` default schema was also inspected.
Create requests use `POST /api/dnsmasq/settings/add_host`, with this JSON wrapper:

```json
{"host":{"host":"git","domain":"eaglepass.io","ip":"10.0.20.226","local":"0"}}
```

Use `local="0"`. Setting it to `1` marks the entire `eaglepass.io` domain local
and prevents forwarding unrelated names. The standard backend also adds the
short host name to its hosts file; the executor rejects conflicting short names,
aliases, wildcard records, duplicate records, or target records with DHCP bindings.
Other existing host overrides remain untouched.

## Check and prepare

From the canonical checkout, with compatible kubectl and existing 1Password CLI access:

```sh
python3 network/scripts/reconcile-private-dns.py
python3 -B network/scripts/test_reconcile_private_dns.py
```

Default mode authenticates through the normal GUI CSRF flow and performs only
read requests after login. It does not create a backup. Existing item references
identify the OPNSense login and controller-verified configuration document in the
`server` vault. No API key is created. No interactive unlock is attempted.

TLS uses `opnsense.localdomain` over an explicit connection to `10.0.0.1`, with
hostname, expiry, chain, and exact certificate checks against the protected
document's referenced GUI certificate. Certificate changes require updating the
authorized trust source; there is no insecure fallback. Cookies and credentials
stay in memory. Errors omit remote response bodies and subprocess output.

Checks include the exact firmware version, current host schema, global rebinding
protection, DNS listener ownership, upstream settings, Unbound settings, and
current ingress LB/TCP-22 ownership. Fingerprints cover the entire selected model,
including other host rows and DHCP settings. Do not run concurrent router changes.
There is no server-side compare-and-swap; checks narrow, but cannot eliminate, the
interval between a read and its following write.

## Disruption and application

**The fixed supported action is `POST /api/dnsmasq/service/restart`.** Expect a brief
DNS interruption. In the verified `25.7.9_7` implementation, this action reads saved
configuration, regenerates both the hosts file and Dnsmasq templates, and starts
Dnsmasq. It applies the repository-owned API rows through the owning device workflow.
It does not invoke the reconfigure action's firewall reload or a Kea service action.
No firewall-pending comparison is needed for this narrower action.

The complete reviewed path uses core commit
`c6ffd18ec3f1c07651fe917093e0a53c342b9e24`, installed Dnsmasq `2.91_1,1`
([ports `25.7.9`](https://github.com/opnsense/ports/blob/25.7.9/dns/dnsmasq/Makefile#L1-L5)),
and installed base `25.7.8`:

| Source | Verified behavior |
| --- | --- |
| [Base service controller, lines 133–141](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/mvc/app/controllers/OPNsense/Base/ApiMutableServiceControllerBase.php#L133-L141) | `restartAction()` sends only `dnsmasq restart` to configd; returns a `response` field. |
| [Dnsmasq actions, lines 11–15](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/service/conf/actions.d/actions_dnsmasq.conf#L11-L15) | Script action runs `pluginctl -s dnsmasq restart`. |
| [pluginctl, lines 125–147 and 250–272](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/sbin/pluginctl#L250-L272) | Selects the named service, then calls `service_control_restart()`, not the general configure path. |
| [util.inc, lines 269–298](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/etc/inc/util.inc#L269-L298) and [Dnsmasq service definition, lines 48–70](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/etc/inc/plugins.inc.d/dnsmasq.inc#L48-L70) | Dispatches the registered PHP restart callback, `dnsmasq_configure_do()`. No firewall or Kea restart callback is registered for this service. |
| [dnsmasq_configure_do, lines 166–194](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/etc/inc/plugins.inc.d/dnsmasq.inc#L166-L194) | Stops the Dnsmasq registration watcher and Dnsmasq, builds host entries, reloads `OPNsense/Dnsmasq` templates, and starts Dnsmasq. The optional ISC registration watcher is disabled in the inspected configuration (`regdhcp=0`). |
| [Host generation, lines 197–263](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/etc/inc/plugins.inc.d/dnsmasq.inc#L197-L263) | Reads persisted host rows into `/var/etc/dnsmasq-hosts`; clears generated `/var/etc/dnsmasq-leases`. Static DHCP registration is disabled (`regdhcpstatic=0`). Neither file is Kea's lease database. |
| [Template action, lines 1–7](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/service/conf/actions.d/actions_template.conf#L1-L7), [inline handler, lines 48–64](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/service/modules/actions/inline.py#L48-L64), and [targets](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/service/templates/OPNsense/Dnsmasq/%2BTARGETS) | Reloads `/conf/config.xml` and renders `/usr/local/etc/dnsmasq.conf` plus `/etc/rc.conf.d/dnsmasq`. No firewall template or post-action hook. |
| [Packaged rc script, lines 43–109](https://github.com/opnsense/ports/blob/25.7.9/dns/dnsmasq/files/dnsmasq.in#L43-L109) | Operates the Dnsmasq binary/PID, checks its configuration, and maintains its timestamp. No firewall/Kea action. |
| [Base rc.subr, lines 1244–1263](https://github.com/opnsense/src/blob/25.7.8/libexec/rc/rc.subr#L1244-L1263) | `_rc_restart_done` prevents recursive restart within a script; it is not a cross-process lock. The callback above invokes separate rc stop/start commands. No separate `restartlock` hook is defined in this reviewed chain. |

The [configd script handler, lines 40–46](https://github.com/opnsense/core/blob/c6ffd18ec3f1c07651fe917093e0a53c342b9e24/src/opnsense/service/modules/actions/script.py#L40-L46)
returns `OK` for a successful process exit. The executor requires exactly
`{"response":"OK"}` and then verifies service status, listeners, and selected
settings. That acknowledgement alone does not prove generated DNS behavior;
post-application DNS/NSS checks remain mandatory. No alternate service action or
firewall-reload flag is exposed. The broader `/service/reconfigure` endpoint is
explicitly excluded from the executor allowlist.

The inspected router uses `kea-dhcp4` on port 67. Dnsmasq has no DHCP ranges or RA
enabled. The executor refuses a Dnsmasq DHCP/RA configuration or DHCP listener:
such a change requires separate impact planning, not an override flag. Kea
listeners and all selected unrelated settings must remain unchanged after apply.

1. Review desired state, executor, tests, and this runbook. Run focused tests and
   default check mode. Obtain deployment authority.
2. Commit and push these scoped files to canonical Gitea `master`. The executor
   requires scoped-clean tracked files, branch `master`, correct origin, and HEAD
   equal to a fresh `git ls-remote origin refs/heads/master` result. It never commits
   or pushes. Unrelated work must be preserved.
3. Supply a private durable recovery directory beneath
   `$HOME/.local/state/homelab/recovery/opnsense`, outside source and temporary/cache
   storage. Ancestors must not be symlinks or writable by other users. The final
   directory must belong to the operator and have mode `0700`; new directories
   use `0700`. Do not use a disposable diagnostics directory for real backups.
4. Run the authorized application:

   ```sh
   python3 network/scripts/reconcile-private-dns.py --apply \
     --backup-dir "$HOME/.local/state/homelab/recovery/opnsense/private-dns"
   ```

Before the first configuration write, the executor downloads the **current full**
`/conf/config.xml` through the supported backup form. It excludes RRD export but
preserves all configuration bytes and metadata. It validates router/certificate
identity, Dnsmasq model version, persisted fields, and host UUIDs against bracketed
live reads. Firmware identity comes from the bracketed firmware API; the XML model
version is not an installed-software version. Backup files are exclusively created
with mode `0600`; existing files are never replaced. Only backup filename/hash,
source identity, field fingerprints, and owned UUIDs enter the durable JSONL receipt.

Missing rows are added individually with an exact fresh state comparison before
each write and exact predicted-state readback afterward. Existing matching rows
are retained. The final supported call is
`POST /api/dnsmasq/service/restart` with `{}`, exactly once, followed by
status/listener/settings checks. An already-configured apply performs no backup,
write, or restart.

These are separate operations, **not an atomic transaction**. A failure stops the
sequence. The executor never retries an uncertain write or deletes rows on its own.
Its failure readback records new/removed UUIDs when available. An acknowledged UUID
is not treated as verified ownership until exact row/state readback passes.

## Rollback

Preserve the backup and receipt. Record the intended rollback through the
repository-first workflow and push that scoped clean state before execution.
The complete apply receipt supplies the exact created UUIDs, per-row hashes, final
state hash, and original backup hash. Preexisting matching rows are never deleted.

```sh
python3 network/scripts/reconcile-private-dns.py --rollback-receipt /protected/path/apply.jsonl
python3 network/scripts/reconcile-private-dns.py --apply \
  --rollback-receipt /protected/path/apply.jsonl \
  --backup-dir "$HOME/.local/state/homelab/recovery/opnsense/private-dns-rollback"
```

Rollback first captures a fresh protected backup of the current configuration.
It refuses altered rows, changed state, foreign UUIDs, changed backup bytes, or an
incomplete apply receipt. It deletes only verified created UUIDs using
`POST /api/dnsmasq/settings/del_host/<uuid>`, checks every deletion, and restarts
once. Partial or uncertain operations require read-only investigation and a new
repository-owned recovery plan; do not manufacture a complete receipt or replay
an add/delete. Whole-router restore is a separate recovery procedure, never the
default rollback for three DNS records.

## Acceptance after application or rollback

- On charmander, pikachu, and sprigatito: query their configured DNS and use NSS
  (`getent ahostsv4`) for all three FQDNs. Application should return `10.0.20.226`.
- Verify `git.eaglepass.io:22` with established SSH host-key verification and a
  read-only Git operation. Do not change its hostname, proxying, or port.
- Verify registry `/v2/` and auth HTTPS with hostname/certificate validation.
- Verify unrelated public names such as `github.com` and `registry.k8s.io`.
- Confirm upstream selection, global rebinding protection, DHCP settings/listeners,
  unrelated host rows, and other selected settings retain their prior fingerprints.
- For a rebinding negative case, select an **existing authorized controlled name**
  outside these overrides, with a known private A answer at the established
  upstream. Confirm upstream answer versus router blocking. Do not create public
  DNS records, disable protection, or reuse a host override as the negative case.
  If no suitable name exists, record this gate as untested.
- Finish the parent maintenance workflow's application and six-layer health gates.
  Executor success alone is not maintenance completion.
