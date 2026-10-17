# Metal SSH trust enrollment

## One-time manual enrollment

From the repository root, run:

```sh
make -C metal ssh-trust
```

This command displays every active inventory node's hostname/IP, Ed25519, ECDSA,
and RSA public-key fingerprints, plus Gitea's RSA fingerprint for **only**
`git.eaglepass.io`. It prints a deterministic batch SHA256 digest and asks once
for `APPROVE <full batch hash>`. Any other answer, EOF, incomplete collection,
changed source identity, or concurrent pointer update refuses enrollment.

Approval explicitly trusts the authenticated Kubernetes cluster as the ongoing
source of these public keys, including subsequent authenticated-source rotations.
It is not an independent hardware attestation. Cluster administrators and writers
of the trust ConfigMap remain inside that trust boundary. No `ssh-keyscan`, SSH
connection, private-key read, arbitrary pod shell, or disabled host check is used.

Prerequisites: Python 3.9+ with the existing PyYAML dependency, compatible
`kubectl` (within one minor version of the server), and the repository's
`metal/kubeconfig.yaml`. Its minified configuration must verify the exact server
`https://10.0.20.50:6443` with its configured CA. TLS/proxy overrides and proxy
environment variables are refused. The helper never prints raw kubeconfig or
kubectl failure diagnostics.

All nine currently active nodes come from uncommented `metal` masters/workers in
`inventories/prod.yml`; `chikorita` is excluded. The API must report exactly those
active nodes, Ready, with matching InternalIP addresses. Every node needs one
ready `monitoring-system` pod labeled
`app.kubernetes.io/name=prometheus-node-exporter`, with container `node-exporter`
mounting hostPath `/` read-only at `/host/root`. The fixed host dynamic loader and
`cat` read exactly the three `/host/root/etc/ssh/ssh_host_*_key.pub` files. The
single ready Gitea pod/container must mount persistent `/data`; only
`/data/ssh/gitea.rsa.pub` is read. Pod UID, node UID, mounts, readiness, and node
addresses and public-key contents are checked again before publication. Replacement during approval
requires rerunning the command.

Preview without any ConfigMap or local-file write:

```sh
python3 metal/scripts/ssh-trust.py --preview
```

## Stored reference and local use

The metal-owned `kube-system/homelab-ssh-trust` ConfigMap stores only public
`known_hosts` and `record.json`. The record includes cluster UID, API server,
source contract, manual or automated provisioning authorization, latest method/time, batch
digest, inventory, and source pod/node identities. The managed-by label is
`app.kubernetes.io/managed-by=homelab-metal-ssh-trust`.

Publication uses create or resourceVersion-guarded replace, never force/apply.
The exact previous pointer is rechecked immediately before publication; exact
GET readback is required before local installation. Replacing an approved pointer
first preserves its complete prior data in an immutable
`homelab-ssh-trust-<first16 SHA256 of prior data>` ConfigMap. Existing archives
are verified, never overwritten or deleted. A failed publication can leave a
verified archive; a failed readback can leave a changed pointer. Neither failure
installs local trust. Inspect the pointer before retrying.

The dedicated local bundle defaults to `~/.ssh/homelab_known_hosts`, installed
atomically with mode `0600`. Existing symlink destinations are refused.
An advisory lock serializes publication and local installation on each operator host.
`~/.ssh/known_hosts` is untouched. No SSH/global configuration is changed. Use
the bundle explicitly with strict checking:

```sh
ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$HOME/.ssh/homelab_known_hosts" user@charmander
git -c core.sshCommand="ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/homelab_known_hosts" ls-remote origin
```

Another operator or future agent can install the approved cluster reference
without collecting pod keys:

```sh
python3 metal/scripts/ssh-trust.py --read
```

`--install` aliases `--read`. Both validate the stored record and current inventory,
then recheck cluster UID and exact pointer before installation. `--known-hosts PATH`
routes only the helper's output file; it does not configure SSH. The record is
public operational data, not a Secret. Restrict Kubernetes write access to the
pointer and archives through existing administrator authorization policy.

## Automated post-provision refresh

After monitoring and Gitea are available:

Use the repository's Ansible toolchain for this target; the Ansible interpreter
must have PyYAML available.

```sh
make -C metal ssh-trust-refresh
# Equivalent localhost-only Ansible invocation:
ansible-playbook --inventory localhost, --connection local metal/ssh-trust.yml
```

The playbook runs `--automatic` locally with the repository cwd and explicit
repository kubeconfig. It reports changed state only when the stored record or
local bundle changes, prints changed/removed fingerprints, and never prompts.
It creates the first reference without prior manual enrollment, and updates it
after inventory changes, key rotations, or cluster reprovisioning. Automated
provisioning is recorded as `automatic`, never misrepresented as human approval.
The authenticated repository kubeconfig is the trust root: TLS, API identity,
complete current inventory, source/key consistency, concurrency and readback
checks remain mandatory. A cluster UID change during a run still fails closed;
a prior record from an old cluster is archived before a fresh authenticated
snapshot replaces it. An unchanged snapshot preserves authorization time
and does not churn the ConfigMap. A pod replacement updates source identity and
therefore the batch even when its keys are unchanged.

The top-level `post-install` target calls this refresh after system/platform
bootstrap. No approval prompt or manual-enrollment prerequisite exists in this
Ansible/post-install path. The separate manual `ssh-trust` command retains its
exact-batch confirmation for an operator-run enrollment.

Both `metal/cluster.yml` and `metal/nodes.yml` also import the same automatic
refresh as delegated, run-once post-tasks. Adding one or several production
inventory nodes therefore updates `kube-system/homelab-ssh-trust` and the
controller's dedicated bundle as part of those playbooks, including runs limited
to just the new hosts. `localhost` does not need to be added to `--limit`.

The refresh reads the full production inventory, waits for exactly one ready
node-exporter on every active node and one ready Gitea source, then publishes
once without a prompt. Readiness waits are bounded convergence checks; API or
authentication errors fail immediately, and publication is never blindly retried.
For tag-filtered runs, include `ssh_trust` when trust refresh is required.

During a completely fresh installation, metal runs before monitoring/Gitea exist.
Only that initial no-reference case, with exactly the four core Kubernetes
namespaces and no platform namespaces, defers publication automatically to
`post-install`. Missing source namespaces with an existing reference are errors,
not a silently skipped node-addition step. The standalone refresh target remains
strict. `ssh_trust_known_hosts` can select the controller's bundle destination;
the default remains `~/.ssh/homelab_known_hosts`.

No trust collection runs during PXE or before authenticated Kubernetes access is
available, so metal bootstrap does not require remote Gitea availability. Existing
`metal/ansible.cfg` sets `host_key_checking=false`; this helper does not rely on
that setting or harden initial bootstrap. Enable strict checking explicitly when
using this reference; changing broader Ansible policy is outside this feature.

## Offline tests

The unit tests mock kubectl/API calls and use `tempfile` for disposable files.
They require PyYAML:

```sh
python3 -B metal/scripts/test_ssh_trust.py
python3 -B -m unittest discover -s metal/scripts -p test_ssh_trust_playbooks.py -v
```

The playbook integration tests require `ansible-core`. They run only the actual
trust-task imports against isolated synthetic inventory/API fixtures, including
two new hosts with `--limit` excluding localhost. They never execute provisioning
roles, SSH, or a live Kubernetes client.

No live enrollment or cluster health claim follows from these offline tests.
