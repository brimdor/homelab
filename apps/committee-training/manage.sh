#!/bin/bash
# Committee Training Job Manager
# Manages training jobs on the homelab Kubernetes cluster (Arcanine node)
#
# Usage:
#   ./manage.sh start [--debug] [--phase PHASE]  - Start a new training job
#   ./manage.sh status                            - Check job status
#   ./manage.sh logs                              - Follow training logs
#   ./manage.sh stop                              - Stop/delete current job
#   ./manage.sh resume CHECKPOINT                 - Resume from checkpoint
#   ./manage.sh shell                             - Open shell in trainer pod

set -e

NAMESPACE="committee-training"
JOB_NAME="committee-pretrain"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
  start [--debug] [--phase PHASE]  Start a new training job
                                   --debug: Run 100 steps only
                                   --phase: pretrain|code|instruct|specialist|consensus
  
  status                           Check job and pod status
  
  logs                             Follow training logs (Ctrl+C to stop)
  
  stop                             Stop and delete current job
  
  resume CHECKPOINT                Resume training from checkpoint path
                                   Example: ./manage.sh resume /checkpoints/step-1000
  
  shell                            Open interactive shell in trainer pod

Examples:
  ./manage.sh start --debug        # Quick test run (100 steps)
  ./manage.sh start --phase pretrain  # Full pre-training
  ./manage.sh logs                 # Watch training progress
  ./manage.sh stop                 # Stop training

EOF
}

check_kubectl() {
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install kubectl."
        exit 1
    fi
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
    
    # Delete existing job if present
    kubectl delete job $JOB_NAME -n $NAMESPACE --ignore-not-found=true 2>/dev/null || true
    
    # Ensure namespace and PVCs exist
    kubectl apply -f "$SCRIPT_DIR/job.yaml" --dry-run=client -o yaml | \
        kubectl apply -f - --selector='!batch.kubernetes.io/job-name'
    
    # Update config
    update_configmap "$phase" "$debug" ""
    
    # Create job
    kubectl apply -f "$SCRIPT_DIR/job.yaml"
    
    log_success "Job created. Waiting for pod to start..."
    
    # Wait for pod
    for i in {1..30}; do
        POD=$(kubectl get pods -n $NAMESPACE -l app=committee-training --no-headers 2>/dev/null | head -1 | awk '{print $1}')
        if [ -n "$POD" ]; then
            STATUS=$(kubectl get pod $POD -n $NAMESPACE -o jsonpath='{.status.phase}' 2>/dev/null)
            log_info "Pod: $POD, Status: $STATUS"
            if [ "$STATUS" = "Running" ]; then
                log_success "Training started! Use './manage.sh logs' to follow."
                exit 0
            fi
        fi
        sleep 2
    done
    
    log_warn "Pod not yet running. Check with: kubectl get pods -n $NAMESPACE"
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
    log_info "Press Ctrl+C to stop following"
    echo ""
    
    kubectl logs -f -n $NAMESPACE $POD -c trainer
}

cmd_stop() {
    log_info "Stopping training job..."
    
    kubectl delete job $JOB_NAME -n $NAMESPACE --ignore-not-found=true
    
    log_success "Job deleted. Checkpoints are preserved in PVC."
}

cmd_resume() {
    local checkpoint="$1"
    
    if [ -z "$checkpoint" ]; then
        log_error "Please specify checkpoint path"
        echo "Usage: ./manage.sh resume /checkpoints/step-1000"
        exit 1
    fi
    
    log_info "Resuming from checkpoint: $checkpoint"
    
    # Delete existing job
    kubectl delete job $JOB_NAME -n $NAMESPACE --ignore-not-found=true 2>/dev/null || true
    sleep 2
    
    # Update config with resume path
    update_configmap "pretrain" "false" "$checkpoint"
    
    # Create job
    kubectl apply -f "$SCRIPT_DIR/job.yaml"
    
    log_success "Resume job created. Use './manage.sh logs' to follow."
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

# Main
check_kubectl

case "${1:-}" in
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
    help|--help|-h)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac
