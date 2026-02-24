Nextcloud deployment (official chart)
===================================

This folder contains manifests and a values file to deploy the official
Nextcloud Helm chart in this homelab using a single NFS export and three
subpaths:

- /mnt/user/nextcloud/data   -> nextcloud-data PV
- /mnt/user/nextcloud/config -> nextcloud-config PV
- /mnt/user/nextcloud/mysql  -> nextcloud-mysql PV

Caution: This will REMOVE existing data in `/mnt/user/nextcloud`. The
user confirmed these files are disposable test data.

Steps performed by this guide:

1) Destructive NAS cleanup (will be executed locally in this repository
   only as a recorded command; do not run automatically on remote hosts):

   sudo rm -rf /mnt/user/nextcloud/*
   sudo mkdir -p /mnt/user/nextcloud/{data,config,mysql}
   sudo chown -R 1000:1000 /mnt/user/nextcloud

   - Adjust the UID:GID to match whatever image you use (linuxserver
     images often use PUID/PGID environment variables). Setting ownership
     to 1000:1000 is a reasonable default for many containers.

2) Install/upgrade from this repo chart (it wraps the official chart and
   also creates the static PV/PVC resources):

   helm repo add nextcloud https://nextcloud.github.io/helm/
   helm repo update
   helm upgrade --install nextcloud apps/nextcloud -n nextcloud

3) Verify deployment:

   kubectl -n nextcloud get pv,pvc
   kubectl -n nextcloud get pods
   kubectl -n nextcloud logs -l app.kubernetes.io/name=nextcloud

Notes & Recommendations:
- Running MariaDB on NFS is not optimal; if you observe issues migrate
  the DB PV to block storage (RBD/LVM) later.
- Keep secrets out of git: prefer `kubectl create secret generic` or use
  external-secrets with 1Password backend.
