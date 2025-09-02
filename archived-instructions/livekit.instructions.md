---
applyTo: '**'
---

Plan: create a standalone Helm chart for "apps/livekit" that is derived from the upstream LiveKit Helm chart (including templates). This document replaces the umbrella/subchart workflow: the chart must include Chart.yaml, values.yaml and the necessary templates so it builds and renders correctly by itself. Use `apps/localai` as the authoritative example for value naming and local repo conventions.

1) Prep / discovery
   - Confirm `apps/livekit` exists in the repository and open `apps/localai/Chart.yaml` and `apps/localai/values.yaml` to copy conventions for keys, nesting and example values.
   - Inspect `apps/localai/templates/` to learn how this repo expects charts to structure templates, volume mounts, sidecars and service/ingress conventions.

2) Use the upstream LiveKit Helm chart as the source
   - Review the upstream LiveKit Helm chart at: https://github.com/livekit/livekit-helm/tree/master/livekit-server to understand standard values and template patterns (image, redis, ingress, service, persistence, configmaps, args).
   - Favor the umbrella repo conventions from `apps/localai` for key names and nesting where the repo is opinionated. Map upstream keys into that structure when they differ.

3) Create a standalone chart for `apps/livekit`
   - Chart layout: `apps/livekit/` must contain at minimum:
     - `Chart.yaml` — minimal, valid Helm metadata (name: livekit, version: 0.1.0, appVersion optional, description), type: application if other charts follow that.
     - `values.yaml` — contains all keys the chart's templates will read (image, redis, persistence, service, ingress, resources, replicaCount, nodeSelector, tolerations, affinity, etc.). Use concrete example values safe for local testing (small PVC, test-friendly tags).
     - `templates/` — copy/adapt the relevant templates from the upstream livekit-server chart (Deployment/StatefulSet, Service, Ingress, ConfigMap, Secret manifests, PersistentVolumeClaim, and helper templates). Do not rely on the umbrella to supply templates.

4) Values mapping and structure
   - `values.yaml` must contain the variables used by the chart's templates. Required top-level keys (example structure; align names to `apps/localai` when repo conventions differ):
     - replicaCount: integer (e.g., 1)
     - image:
       - repository: string
       - tag: string
       - pullPolicy: string
     - redis: (sidecar or external)
       - enabled: boolean
       - image:
         - repository: string
         - tag: string
         - pullPolicy: string
       - port: integer
       - resources: map (requests/limits)
       - env: map of environment variables (if needed)
     - service:
       - enabled: boolean
       - type: ClusterIP|NodePort|LoadBalancer
       - port: integer
       - targetPort: integer
       - annotations: map
     - ingress:
       - enabled: boolean
       - annotations: map
       - hosts: list of host/path entries
       - tls: list with hosts and secretName (optional)
     - persistence:
       - enabled: boolean
       - storageClass: string|null
       - accessMode: ReadWriteOnce
       - size: e.g., 10Gi
       - mountPath: string
     - resources: map (requests/limits for main container)
     - nodeSelector, tolerations, affinity: scheduling fields
     - extraArgs/config: LiveKit-specific argument/config blocks the templates reference

   - Populate `values.yaml` with reasonable concrete defaults suitable for local/dev clusters (small PVCs, example hostnames, and non-privileged images). Use `apps/localai/values.yaml` as the format reference for naming.

5) Templates: include and adapt upstream templates
   - Copy or adapt the template files from the upstream LiveKit chart into `apps/livekit/templates/` and modify them to follow your repo conventions (labels, selectors, volumeMounts, sidecar naming). Key template types to include:
     - Deployment or StatefulSet (main LiveKit container)
     - Service
     - Ingress
     - PersistentVolumeClaim(s)
     - ConfigMap(s) for LiveKit config
     - Optional: Secret manifests or instructions to provide secrets externally
     - Helper/_helpers.tpl for common template helpers

   - For a sidecar Redis option, implement either an extra-container in the same pod (sidecar) or a dependency to an existing Redis chart — follow `apps/localai/templates` for how sidecars are expressed in this repo.

6) Validation and local testing (run from workspace root)
   - Lint the chart:
     - helm lint apps/livekit
   - Render manifests to verify templates and values substitution:
     - helm template apps/livekit --values apps/livekit/values.yaml
     - Inspect rendered manifests for the presence of:
       - Pod/Deployment with the LiveKit container and (if enabled) Redis sidecar
       - Service for the LiveKit ports
       - Ingress with expected host and TLS
       - PVC manifests and volumeMounts
   - Install to a test namespace:
     - kubectl create namespace livekit-test
     - helm upgrade --install livekit apps/livekit -n livekit-test --create-namespace
     - kubectl -n livekit-test get pods,svc,ing,pvc
     - kubectl -n livekit-test get pod -l app=livekit -o yaml (confirm containers and mounts)

7) Troubleshooting notes
   - If resources don't appear or are misconfigured:
     - Double-check the `values.yaml` keys used by your templates match what you populated.
     - Compare `apps/localai/values.yaml` keys and `templates/` label/selector conventions.
   - If Redis sidecar doesn't appear:
     - Ensure your templates look for the same key name (e.g., `.Values.redis.enabled` or `.Values.sidecars.redis`) that you defined in `values.yaml`.
   - If PVCs don't bind:
     - Verify the cluster has an appropriate StorageClass and that `storageClass` in `values.yaml` is correct.
   - If Ingress isn't reachable:
     - Ensure an ingress controller is installed in the cluster and host DNS resolves to the cluster IP.

8) Minimal acceptance criteria
   - `apps/livekit/Chart.yaml` exists and is syntactically valid.
   - `apps/livekit/values.yaml` contains keys that the chart's `templates/` expect (image, redis, persistence, ingress, service, resources).
   - `helm template apps/livekit` renders complete manifests (deployment/statefulset, service, ingress, pvc) without template errors.
   - `helm upgrade --install` in a test namespace deploys resources and the LiveKit pod reaches Running with both main container and redis sidecar (if enabled).

9) Notes / constraints
   - This approach intentionally creates a self-contained chart for `apps/livekit` that does not rely on an umbrella to supply templates. The umbrella pattern is replaced with an upstream-derived chart plus repo-specific adaptations.
   - Keep key names consistent with `apps/localai` where this repo is opinionated—this reduces editing and ensures consistent rendering across apps.

10) Deliverables (explicit checklist)
   - `apps/livekit/Chart.yaml` — minimal Helm metadata.
   - `apps/livekit/values.yaml` — concrete example values for image, redis (sidecar), ingress, service, persistence, resources, scheduling.
   - `apps/livekit/templates/` — templates adapted from the upstream LiveKit Helm chart sufficient to render Deployment/StatefulSet, Service, Ingress, PVC, ConfigMap and helper templates.
   - Validation steps documented above and validated locally with `helm template` and `helm upgrade --install`.

End of