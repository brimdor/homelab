# Private service DNS on OPNSense

`network/configs/dnsmasq-private-hosts.json` owns exactly eleven reviewed Dnsmasq
DNS host overrides, all pointing to the ingress controller at `10.0.20.226`.
The executor's fixed `NAMES` allowlist must match this complete set. It never
discovers hosts at runtime or permits wildcard/domain-wide exceptions. Update the
reviewed desired state if ingress ownership changes. Public DNS publishes this
private address; these internal answers preserve direct access, including Git SSH
on port 22, without Cloudflare proxying.

## Verified private-ingress coverage and 3-to-11 migration

The October 19, 2026 survey at repository revision
`855b5af7a08baa915c99203bb95c5720a5dc5db0` found the following coverage. Every listed
chart is active under the canonical Gitea `master` discovery rules. Its Application
was `Synced`/`Healthy` at that revision, with ready backend pods, endpoints, and
updated controllers. All ingresses use `nginx`, have LB address `10.0.20.226`, and
omit the ExternalDNS target annotation. The source declarations and live ownership
were checked independently; the absent annotation alone does not prove private DNS.

All names below use the suffix `.eaglepass.io`. Direct `dig` from trusted
`charmander` queried public upstream `1.1.1.1` and configured router `10.0.20.1`.

| Host | Owning chart | Upstream A | Router result before expansion | Disposition |
| --- | --- | --- | --- | --- |
| `git` | `platform/gitea` | `10.0.20.226` | `10.0.20.226` | Preserve existing row |
| `registry` | `platform/zot` | `10.0.20.226` | `10.0.20.226` | Preserve existing row |
| `auth` | `platform/kanidm` | `10.0.20.226` | `10.0.20.226` | Preserve existing row |
| `argocd` | `system/argocd` | `10.0.20.226` | No answer, EDE 15 | Add exact host |
| `dex` | `platform/dex` | `10.0.20.226` | No answer, EDE 15 | Add exact host |
| `grafana` | `platform/grafana` | `10.0.20.226` | No answer, EDE 15 | Add exact host |
| `radarr` | `apps/radarr` | `10.0.20.226` | No answer, EDE 15 | Add exact host |
| `sabnzbd` | `apps/sabnzbd` | `10.0.20.226` | No answer, EDE 15 | Add exact host |
| `searxng` | `apps/searxng` | `10.0.20.226` | No answer, EDE 15 | Add exact host |
| `sonarr` | `apps/sonarr` | `10.0.20.226` | No answer, EDE 15 | Add exact host |
| `ci` | `platform/woodpecker` | `10.0.20.226` | No answer, EDE 15 | Add exact host |
| `omni-tools-canary` | `apps/omni-tools-canary` | `104.21.70.102`, `172.67.222.216` | Same public addresses | Exclude: public Cloudflare addresses |

The eleven included names cover the proven private-address hosts in the surveyed
active ingress set. `omni-tools-canary` is active and ready, but its public answers
exclude it from this repair. No inactive or other-address name is added.

The original three-row repair was deployed at `855b5af7`; this expansion is a
separate rollout. Default check mode must report exactly the eight missing names
above and retain the original three UUIDs and complete row fingerprints. After
review and the normal commit/push gates, a new apply captures its own current full
protected backup and receipt, adds only those eight rows, and restarts once.
The count checks use `len(NAMES)` against the fixed reviewed set, not an arbitrary
caller-supplied count. No TLS, firmware/model, backup, consumer, DHCP, or preservation
gate is relaxed by the expanded scope.

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
default rollback for these DNS records.

Keep the original three-row recovery pair
`20261019T000905Z-9fabf7121304422591484d8cdf9287c4.{xml,jsonl}` unchanged in protected
recovery storage. Its complete receipt remains supported for its recorded final
state. It must fail the state-drift guard after the eight new rows are applied.
The expansion's separate receipt owns only its newly created UUIDs; rolling back
that batch deletes only those rows and preserves `git`, `registry`, and `auth`.
Never rewrite the earlier receipt or automatically chain rollbacks. Each authorized
rollback takes its own fresh backup and must satisfy its exact recorded-state guard.

## Acceptance after application or rollback

- On charmander, pikachu, and sprigatito: query their configured DNS and use NSS
  (`getent ahostsv4`) for all eleven approved FQDNs. Application should return
  `10.0.20.226`; confirm the original three row UUIDs and contents are unchanged.
- Verify the eight newly covered applications through their expected HTTPS routes,
  with hostname/certificate validation and each application's normal status or
  authentication redirect. Preserve `omni-tools-canary`'s public DNS behavior.
- Verify `git.eaglepass.io:22` with established SSH host-key verification and a
  read-only Git operation. Do not change its hostname, proxying, or port.
- Verify registry `/v2/` and auth HTTPS with hostname/certificate validation.
- Verify unrelated public names such as `github.com` and `registry.k8s.io`.
- Confirm upstream selection, global rebinding protection, DHCP settings/listeners,
  unrelated host rows, and other selected settings retain their prior fingerprints.
- Retain the pre-expansion `argocd.eaglepass.io` EDE 15 result as historical negative
  control evidence. It also exposed a legitimate private application's coverage
  gap; after expansion, Argo CD must resolve normally. Never leave an active private
  application blocked merely to provide a negative test. If a new negative case is
  needed, use an existing authorized controlled name outside legitimate application
  coverage. Do not create public DNS or disable protection. If no suitable case
  exists, report that new post-expansion control as untested and preserve the prior
  evidence plus the unchanged global protection setting.
- Finish the parent maintenance workflow's application and six-layer health gates.
  Executor success alone is not maintenance completion.
