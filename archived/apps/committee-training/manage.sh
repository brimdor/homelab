#!/bin/bash
# Committee Training Job Manager
# Manages training jobs on the homelab Kubernetes cluster (Arcanine node)
#
# Usage:
#   ./manage.sh sync                              - Sync local code to cluster
#   ./manage.sh start [--debug] [--phase PHASE]  - Start a new training job
#   ./manage.sh status                            - Check job status
#   ./manage.sh logs                              - Follow training logs
#   ./manage.sh stop                              - Stop/delete current job
#   ./manage.sh resume CHECKPOINT                 - Resume from checkpoint
#   ./manage.sh shell                             - Open shell in trainer pod
#
# Resource Management:
#   This script automatically scales down Ollama and LocalAI on Arcanine
#   before starting training, and restores them when training stops.
#   This is necessary because Arcanine has limited resources and cannot
#   run both inference services and training simultaneously.

set -e

NAMESPACE="committee-training"
JOB_NAME="committee-pretrain"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMITTEE_REPO="${COMMITTEE_REPO:-$HOME/Documents/GitHub/committee}"

# Services to scale down during training (namespace/deployment)
# These run on Arcanine and compete for GPU/CPU/memory
CONFLICTING_SERVICES=(
    "ollama/ollama"
    "localai/localai-local-ai"
)

# ArgoCD applications that manage these services (need to pause sync)
ARGOCD_APPS=(
    "ollama"
    "localai"
)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

show_help() {
    cat << EOF
Committee Training Job Manager
==============================

Commands:
  sync                             Sync local code to cluster PVC (run first!)
  
  start [--debug] [--phase PHASE]  Start a new training job
                                   --debug: Run 100 steps only
                                   --phase: pretrain|code|instruct|specialist|consensus
  
  status                           Check job and pod status
  
  logs                             Follow training logs (Ctrl+C to stop)
  
  stop                             Stop and delete current job (restores services)
  
  resume CHECKPOINT                Resume training from checkpoint path
                                   Example: ./manage.sh resume /checkpoints/step-1000
  
  shell                            Open interactive shell in trainer pod
  
  restore-services                 Manually restore Ollama/LocalAI if needed

Resource Management:
  Training automatically scales down Ollama and LocalAI on Arcanine to free
  GPU and CPU resources. These services are restored when you run 'stop'.

First Time Setup:
  1. ./manage.sh sync              # Copy code to cluster
  2. ./manage.sh start --debug     # Test run

Examples:
  ./manage.sh sync                 # Sync latest code
  ./manage.sh start --debug        # Quick test run (100 steps)
  ./manage.sh start --phase pretrain  # Full pre-training
  ./manage.sh logs                 # Watch training progress
  ./manage.sh stop                 # Stop training, restore services

EOF
}

check_kubectl() {
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install kubectl."
        exit 1
    fi
}

# Sync local Committee code to the cluster PVC
cmd_sync() {
    log_info "Syncing Committee code to cluster..."
    
    # Check that committee repo exists
    if [ ! -d "$COMMITTEE_REPO/training" ]; then
        log_error "Committee repo not found at: $COMMITTEE_REPO"
        log_error "Set COMMITTEE_REPO environment variable to the correct path."
        exit 1
    fi
    
    log_info "Source: $COMMITTEE_REPO"
    
    # Ensure namespace exists
    kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    
    # Check if PVC exists, create if not
    if ! kubectl get pvc committee-code -n $NAMESPACE &>/dev/null; then
        log_info "Creating PVC..."
        kubectl apply -f - << EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: committee-code
  namespace: $NAMESPACE
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard-rwo
  resources:
    requests:
      storage: 10Gi
EOF
        # Wait for PVC to be bound
        log_info "Waiting for PVC to be ready..."
        kubectl wait --for=jsonpath='{.status.phase}'=Bound pvc/committee-code -n $NAMESPACE --timeout=60s
    else
        log_info "PVC already exists"
    fi
    
    # Create a temporary pod to receive the files
    log_info "Creating sync pod..."
    kubectl delete pod code-sync -n $NAMESPACE --ignore-not-found=true 2>/dev/null || true
    sleep 2
    
    kubectl apply -f - << EOF
apiVersion: v1
kind: Pod
metadata:
  name: code-sync
  namespace: $NAMESPACE
spec:
  restartPolicy: Never
  containers:
    - name: sync
      image: busybox:latest
      command: ["sleep", "3600"]
      volumeMounts:
        - name: code
          mountPath: /code
  volumes:
    - name: code
      persistentVolumeClaim:
        claimName: committee-code
EOF
    
    # Wait for pod to be ready
    log_info "Waiting for sync pod to be ready..."
    kubectl wait --for=condition=Ready pod/code-sync -n $NAMESPACE --timeout=120s
    
    # Clear existing code
    log_info "Clearing existing code..."
    kubectl exec -n $NAMESPACE code-sync -- rm -rf /code/committee
    kubectl exec -n $NAMESPACE code-sync -- mkdir -p /code/committee
    
    # Copy training code (exclude large/unnecessary files)
    log_info "Copying training code..."
    
    # Create tar of essential files and pipe to pod
    (cd "$COMMITTEE_REPO" && tar cf - \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.coverage' \
        --exclude='*.egg-info' \
        --exclude='.pytest_cache' \
        --exclude='wandb' \
        --exclude='checkpoints' \
        training data config.yaml Modelfile 2>/dev/null) | \
        kubectl exec -i -n $NAMESPACE code-sync -- tar xf - -C /code/committee
    
    # Verify copy
    log_info "Verifying code..."
    kubectl exec -n $NAMESPACE code-sync -- ls -la /code/committee/
    kubectl exec -n $NAMESPACE code-sync -- ls -la /code/committee/training/
    
    # Check for train.py
    if kubectl exec -n $NAMESPACE code-sync -- test -f /code/committee/training/scripts/train.py; then
        log_success "Code sync complete!"
    else
        log_error "Code sync failed - train.py not found"
        exit 1
    fi
    
    # Cleanup sync pod
    log_info "Cleaning up sync pod..."
    kubectl delete pod code-sync -n $NAMESPACE --ignore-not-found=true
    
    log_success "Code synced successfully. You can now run './manage.sh start'"
}

# Scale down services that conflict with training on Arcanine
scale_down_conflicting_services() {
    log_info "Scaling down conflicting services on Arcanine..."
    
    # First, suspend ArgoCD auto-sync to prevent reconciliation
    # We need to remove the 'automated' key entirely and also patch selfHeal
    log_info "Suspending ArgoCD auto-sync..."
    for app in "${ARGOCD_APPS[@]}"; do
        if kubectl get application "$app" -n argocd &>/dev/null; then
            # Use strategic merge to disable automated sync
            kubectl patch application "$app" -n argocd --type=strategic \
                -p '{"spec":{"syncPolicy":{"automated":null}}}' 2>/dev/null || true
            # Also try JSON patch to remove automated entirely
            kubectl patch application "$app" -n argocd --type=json \
                -p '[{"op":"replace","path":"/spec/syncPolicy/automated","value":null}]' 2>/dev/null || true
            log_info "  Attempted to suspend sync for: $app"
        fi
    done
    
    # Give ArgoCD a moment to stop syncing
    sleep 3
    
    for service in "${CONFLICTING_SERVICES[@]}"; do
        local ns="${service%/*}"
        local deploy="${service#*/}"
        
        # Check current replicas
        local replicas=$(kubectl get deployment "$deploy" -n "$ns" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
        
        if [ "$replicas" != "0" ]; then
            log_info "  Scaling down $ns/$deploy (was $replicas replicas)"
            kubectl scale deployment "$deploy" -n "$ns" --replicas=0
        else
            log_info "  $ns/$deploy already scaled to 0"
        fi
    done
    
    # Force delete pods if they still exist after scale down
    log_info "Waiting for services to stop (force-deleting if needed)..."
    sleep 5
    
    for service in "${CONFLICTING_SERVICES[@]}"; do
        local ns="${service%/*}"
        local deploy="${service#*/}"
        
        # Get pods for this deployment
        local pods=$(kubectl get pods -n "$ns" -l "app.kubernetes.io/name=$(echo $deploy | sed 's/.*-//')" --no-headers 2>/dev/null | awk '{print $1}')
        
        if [ -n "$pods" ]; then
            log_info "  Force deleting pods in $ns..."
            for pod in $pods; do
                kubectl delete pod "$pod" -n "$ns" --grace-period=1 --force 2>/dev/null || true
            done
        fi
    done
    
    # Final check - wait for pods to actually be gone
    for i in {1..10}; do
        local total_pods=0
        for service in "${CONFLICTING_SERVICES[@]}"; do
            local ns="${service%/*}"
            local deploy="${service#*/}"
            local count=$(kubectl get pods -n "$ns" -l "app.kubernetes.io/instance=$deploy" --no-headers 2>/dev/null | grep -v Completed | wc -l)
            total_pods=$((total_pods + count))
        done
        
        if [ "$total_pods" -eq 0 ]; then
            break
        fi
        log_info "  Still waiting for $total_pods pod(s) to terminate..."
        sleep 3
    done
    
    log_success "Conflicting services scaled down"
}

# Restore services after training
restore_conflicting_services() {
    log_info "Restoring services on Arcanine..."
    
    for service in "${CONFLICTING_SERVICES[@]}"; do
        local ns="${service%/*}"
        local deploy="${service#*/}"
        
        log_info "  Scaling up $ns/$deploy to 1 replica"
        kubectl scale deployment "$deploy" -n "$ns" --replicas=1 2>/dev/null || \
            log_warn "  Could not scale $ns/$deploy (may not exist)"
    done
    
    # Re-enable ArgoCD auto-sync
    log_info "Re-enabling ArgoCD auto-sync..."
    for app in "${ARGOCD_APPS[@]}"; do
        if kubectl get application "$app" -n argocd &>/dev/null; then
            # Restore auto-sync with prune and self-heal
            kubectl patch application "$app" -n argocd --type=merge \
                -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}' 2>/dev/null || \
                log_warn "  Could not re-enable sync for $app"
            log_info "  Re-enabled sync for ArgoCD app: $app"
        fi
    done
    
    log_success "Services restored. They may take a minute to become ready."
}

update_configmap() {
    local phase="${1:-pretrain}"
    local debug="${2:-false}"
    local resume="${3:-}"
    
    log_info "Updating ConfigMap..."
    kubectl apply -f - << EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: committee-training-config
  namespace: $NAMESPACE
data:
  TRAINING_PHASE: "$phase"
  MAX_STEPS: "0"
  RESUME_FROM_CHECKPOINT: "$resume"
  DEBUG_MODE: "$debug"
  WANDB_PROJECT: "committee-1.5b"
  WANDB_MODE: "offline"
EOF
}

cmd_start() {
    local debug="false"
    local phase="pretrain"
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --debug)
                debug="true"
                shift
                ;;
            --phase)
                phase="$2"
                shift 2
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    log_info "Starting Committee training job..."
    log_info "  Phase: $phase"
    log_info "  Debug: $debug"
    log_info "  Node: Arcanine (RTX 3090, 24GB VRAM)"
    echo ""
    
    # Scale down conflicting services first (includes ArgoCD sync suspend)
    scale_down_conflicting_services
    echo ""
    
    # Delete existing job if present
    log_info "Cleaning up any existing job..."
    kubectl delete job $JOB_NAME -n $NAMESPACE --ignore-not-found=true 2>/dev/null || true
    sleep 3
    
    # Ensure namespace exists
    kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

    # Apply PVCs first (pvcs.yaml) - handles already-existing PVCs gracefully
    log_info "Ensuring PVCs exist..."
    kubectl apply -f "$SCRIPT_DIR/pvcs.yaml" 2>/dev/null || true

    # Apply ConfigMap and Job (job-only.yaml doesn't include PVCs)
    log_info "Ensuring ConfigMap and Job exist..."
    kubectl apply -f "$SCRIPT_DIR/job-only.yaml" 2>/dev/null || true

    # Update config with current settings
    update_configmap "$phase" "$debug" ""

    log_success "Job created. Waiting for pod to start..."
    
    # Wait for pod
    for i in {1..60}; do
        POD=$(kubectl get pods -n $NAMESPACE -l app=committee-training --no-headers 2>/dev/null | head -1 | awk '{print $1}')
        if [ -n "$POD" ]; then
            STATUS=$(kubectl get pod $POD -n $NAMESPACE -o jsonpath='{.status.phase}' 2>/dev/null)
            log_info "Pod: $POD, Status: $STATUS"
            if [ "$STATUS" = "Running" ]; then
                echo ""
                log_success "Training started! Use './manage.sh logs' to follow."
                log_info "When done, run './manage.sh stop' to restore Ollama/LocalAI."
                exit 0
            fi
        fi
        sleep 2
    done
    
    log_warn "Pod not yet running. Check with: kubectl get pods -n $NAMESPACE"
    log_warn "If pod fails, run './manage.sh stop' to restore services."
}

cmd_status() {
    log_info "Checking training status..."
    echo ""
    
    echo "=== Namespace ==="
    kubectl get namespace $NAMESPACE 2>/dev/null || echo "Namespace not found"
    echo ""
    
    echo "=== Job ==="
    kubectl get job -n $NAMESPACE 2>/dev/null || echo "No jobs found"
    echo ""
    
    echo "=== Pods ==="
    kubectl get pods -n $NAMESPACE 2>/dev/null || echo "No pods found"
    echo ""
    
    echo "=== PVCs ==="
    kubectl get pvc -n $NAMESPACE 2>/dev/null || echo "No PVCs found"
    echo ""
    
    echo "=== Conflicting Services Status ==="
    for service in "${CONFLICTING_SERVICES[@]}"; do
        local ns="${service%/*}"
        local deploy="${service#*/}"
        local replicas=$(kubectl get deployment "$deploy" -n "$ns" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "N/A")
        local ready=$(kubectl get deployment "$deploy" -n "$ns" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        echo "  $ns/$deploy: $ready/$replicas ready"
    done
    echo ""
    
    # Show GPU usage on Arcanine if pod is running
    POD=$(kubectl get pods -n $NAMESPACE -l app=committee-training --no-headers 2>/dev/null | grep Running | head -1 | awk '{print $1}')
    if [ -n "$POD" ]; then
        echo "=== GPU Status ==="
        kubectl exec -n $NAMESPACE $POD -- nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv 2>/dev/null || echo "Could not query GPU"
    fi
}

cmd_logs() {
    POD=$(kubectl get pods -n $NAMESPACE -l app=committee-training --no-headers 2>/dev/null | head -1 | awk '{print $1}')
    
    if [ -z "$POD" ]; then
        log_error "No training pod found. Start a job first."
        exit 1
    fi
    
    log_info "Following logs for pod: $POD"
    log_info "Press Ctrl+C to stop following (training continues)"
    log_info "Run './manage.sh stop' when training completes to restore services."
    echo ""
    
    kubectl logs -f -n $NAMESPACE $POD -c trainer
}

cmd_stop() {
    log_info "Stopping training job..."
    
    kubectl delete job $JOB_NAME -n $NAMESPACE --ignore-not-found=true
    
    log_success "Job deleted. Checkpoints are preserved in PVC."
    echo ""
    
    # Restore services
    restore_conflicting_services
}

cmd_resume() {
    local checkpoint="$1"
    
    if [ -z "$checkpoint" ]; then
        log_error "Please specify checkpoint path"
        echo "Usage: ./manage.sh resume /checkpoints/step-1000"
        exit 1
    fi
    
    log_info "Resuming from checkpoint: $checkpoint"
    
    # Scale down conflicting services
    scale_down_conflicting_services
    echo ""
    
    # Delete existing job
    kubectl delete job $JOB_NAME -n $NAMESPACE --ignore-not-found=true 2>/dev/null || true
    sleep 2
    
    # Update config with resume path
    update_configmap "pretrain" "false" "$checkpoint"
    
    # Create job
    kubectl apply -f "$SCRIPT_DIR/job.yaml"
    
    log_success "Resume job created. Use './manage.sh logs' to follow."
    log_info "When done, run './manage.sh stop' to restore services."
}

cmd_shell() {
    POD=$(kubectl get pods -n $NAMESPACE -l app=committee-training --no-headers 2>/dev/null | grep Running | head -1 | awk '{print $1}')
    
    if [ -z "$POD" ]; then
        log_error "No running training pod found."
        exit 1
    fi
    
    log_info "Opening shell in pod: $POD"
    kubectl exec -it -n $NAMESPACE $POD -c trainer -- /bin/bash
}

cmd_restore_services() {
    restore_conflicting_services
}

# Main
check_kubectl

case "${1:-}" in
    sync)
        cmd_sync
        ;;
    start)
        shift
        cmd_start "$@"
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    stop)
        cmd_stop
        ;;
    resume)
        cmd_resume "$2"
        ;;
    shell)
        cmd_shell
        ;;
    restore-services)
        cmd_restore_services
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac
