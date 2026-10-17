# Add or remove nodes

Or how to scale vertically. To replace the same node with a clean OS, remove it and add it again.

## Add new nodes

!!! tip

    You can add multiple nodes at the same time

Add each node to `metal/inventories/prod.yml` **at the end of the group**
(`masters` or `workers`). Use its verified address, MAC, installation disk and
interface; the following is an example, not an authorized provisioning target:

```diff title="metal/inventories/prod.yml"
diff --git a/metal/inventories/prod.yml b/metal/inventories/prod.yml
index 7f6474a..1bb2cbc 100644
--- a/metal/inventories/prod.yml
+++ b/metal/inventories/prod.yml
@@ -8,3 +8,4 @@ metal:
     workers:
       hosts:
         sprigatito: {ansible_host: 10.0.20.20, mac: '4c:cc:6a:34:dc:6d', disk: sda, network_interface: eno1}
+        new-worker: {ansible_host: 10.0.20.21, mac: '00:11:22:33:44:55', disk: sda, network_interface: eno1}
```

Review and commit the inventory and any required configuration changes, then
push them to canonical Gitea `master` before applying them. Do not edit a live
workload as a replacement for repository-owned desired state.

!!! danger

    PXE provisioning can erase the selected installation disks. Review exact
    hosts, disks, backup/restore evidence and rollback before executing it.
    The initial PXE-rendering stage still reads the full inventory; `limit`
    scopes the subsequent host plays and does not make PXE setup a safe test.
    Never run the default provisioning target as validation.

For an authorized, reviewed provisioning run, install and configure only the
intended new hosts. For example, after replacing the example names with the
approved inventory targets:

```sh
make -C metal boot cluster nodes limit='new-worker,new-worker-2'
```

The `cluster.yml` and `nodes.yml` post-tasks automatically wait for the full
active inventory's public-key sources, collect the new host keys through the
authenticated Kubernetes API, and update the cluster trust ConfigMap and the
controller's dedicated `known_hosts` bundle. No approval or separate enrollment
command is required. Delegation still runs when `--limit` excludes localhost.

During first-ever platform bootstrap, publication automatically defers until
monitoring and Gitea are installed, then runs in the top-level `post-install`
workflow. Existing clusters fail the node-addition step if required trust sources
are missing; they do not silently declare collection complete.

See `metal/README.md` for storage, validation,
manual inspection and noninteractive refresh details. Verify actual node
readiness and the updated trust record after the run; static tests do not prove
that a physical machine joined successfully.

## Remove a node

!!! danger

    It is recommended to remove nodes one at a time

Remove it from the inventory:

```diff title="metal/inventories/prod.yml"
diff --git a/metal/inventories/prod.yml b/metal/inventories/prod.yml
index 7f6474a..d12b50a 100644
--- a/metal/inventories/prod.yml
+++ b/metal/inventories/prod.yml
@@ -4,7 +4,6 @@ metal:
       hosts:
         metal0: {ansible_host: 192.168.1.110, mac: '00:23:24:d1:f3:f0', disk: sda, network_interface: eno1}
         metal1: {ansible_host: 192.168.1.111, mac: '00:23:24:d1:f4:d6', disk: sda, network_interface: eno1}
-        metal2: {ansible_host: 192.168.1.112, mac: '00:23:24:e7:04:60', disk: sda, network_interface: eno1}
     workers:
       hosts:
         metal3: {ansible_host: 192.168.1.113, mac: '00:23:24:d1:f5:69', disk: sda, network_interface: eno1}
```

Drain the node:

```sh
kubectl drain ${NODE_NAME} --delete-emptydir-data --ignore-daemonsets --force
```

Remove the node from the cluster

```sh
kubectl delete node ${NODE_NAME}
```

Shutdown the node:

```
ssh root@${NODE_IP} poweroff
```
