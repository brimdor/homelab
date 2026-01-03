# Homelab Training Guide

This guide explains how to run Committee model training on Chris's homelab Kubernetes cluster using the Arcanine node (RTX 3090, 24GB VRAM).

## Overview

The homelab cluster has a dedicated GPU node called **Arcanine** with an NVIDIA RTX 3090 (24GB VRAM). This node is tainted to prevent regular workloads from scheduling on it - only GPU workloads with the proper tolerations can run there.

## Hardware Configuration

| Location | GPU | VRAM | Use Case |
|----------|-----|------|----------|
| Local Workstation | AMD RX 9070 XT | 16GB | Development, daily use |
| Homelab (Arcanine) | NVIDIA RTX 3090 | 24GB | Training jobs, inference |

**Recommendation**: Run long training jobs on Arcanine to keep your local GPU free for other work.

## Quick Start

### Prerequisites

1. `kubectl` configured to access the homelab cluster
2. Access to the `homelab` repository

### Run Training

```bash
# Navigate to homelab apps
cd ~/Documents/GitHub/homelab/apps/committee-training

# Start a quick test run (100 steps)
./manage.sh start --debug

# Check status
./manage.sh status

# Follow logs
./manage.sh logs

# Stop training
./manage.sh stop
```

### Full Pre-training

```bash
# Start full pre-training (7-8 hours)
./manage.sh start --phase pretrain

# Follow progress
./manage.sh logs
```

### Resume from Checkpoint

```bash
# List checkpoints (open shell first)
./manage.sh shell
ls /checkpoints/

# Resume from a checkpoint
./manage.sh resume /checkpoints/step-10000
```

## Management Commands

| Command | Description |
|---------|-------------|
| `./manage.sh start` | Start new training job |
| `./manage.sh start --debug` | Run 100 steps only (test) |
| `./manage.sh start --phase pretrain` | Specify training phase |
| `./manage.sh status` | Check job/pod status |
| `./manage.sh logs` | Follow training logs |
| `./manage.sh stop` | Stop current job |
| `./manage.sh resume PATH` | Resume from checkpoint |
| `./manage.sh shell` | Open shell in trainer pod |

## Training Phases

| Phase | Description | Duration (RTX 3090) |
|-------|-------------|---------------------|
| `pretrain` | General text (TinyStories, Wikipedia) | ~7-8 hours |
| `code` | Code understanding (FineWeb-Edu subset) | ~4-5 hours |
| `instruct` | Instruction following | ~2-3 hours |
| `specialist` | Committee consensus behavior | ~2 hours |
| `consensus` | Multi-perspective generation | ~1-2 hours |

## Architecture

```
homelab/apps/committee-training/
├── Dockerfile          # Training container image
├── job.yaml           # Kubernetes Job + PVCs + ConfigMap
├── manage.sh          # Management script
└── README.md          # This file
```

The job manifest includes:
- **Namespace**: `committee-training`
- **PVC**: `committee-checkpoints` (100GB) - Persists checkpoints
- **PVC**: `committee-code` (10GB) - Cloned repository
- **ConfigMap**: Training parameters
- **Job**: Training workload with GPU

### Arcanine Node Scheduling

The job uses tolerations and node affinity to schedule on Arcanine:

```yaml
tolerations:
  - key: "dedicated"
    value: "arcanine"
    effect: "NoSchedule"

affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values:
                - "arcanine"
```

## Storage

Checkpoints are persisted to a 100GB PVC mounted at `/checkpoints`. This survives job restarts and deletions.

HuggingFace cache is stored inside the checkpoint volume at `/checkpoints/hf_cache`.

## Monitoring

### GPU Usage

```bash
# Quick GPU check
./manage.sh status

# Detailed nvidia-smi
./manage.sh shell
nvidia-smi -l 1
```

### Training Metrics

Training logs include:
- Step number and loss
- Learning rate
- Tokens per second
- Memory usage
- Checkpoint saves

## Troubleshooting

### Pod stuck in Pending

Check if Arcanine node is available:
```bash
kubectl get nodes
kubectl describe node arcanine
```

### Out of Memory

Reduce batch size in `training/configs/committee_pretrain.yaml`:
```yaml
training:
  per_device_train_batch_size: 2  # Reduce from 4
  gradient_accumulation_steps: 8  # Increase to compensate
```

### Slow Training

Check if Flash Attention is available:
```bash
./manage.sh shell
python -c "import flash_attn; print('Flash Attention available')"
```

### Clone Fails

If the init container can't clone the repo, check:
1. Network connectivity
2. Git repo is public or credentials are configured
3. Branch exists

## Local vs Homelab Training

When starting training, always consider which GPU to use:

| Scenario | Recommended GPU |
|----------|-----------------|
| Quick test (< 100 steps) | Local (AMD RX 9070 XT) |
| Long training (hours) | Homelab (RTX 3090) |
| Need to use local machine | Homelab (RTX 3090) |
| Debugging code changes | Local (faster iteration) |

### Local Training

```bash
cd ~/Documents/GitHub/committee/training
./scripts/run_committee_pretrain.sh --test
```

### Homelab Training

```bash
cd ~/Documents/GitHub/homelab/apps/committee-training
./manage.sh start --phase pretrain
```

## Next Steps After Training

1. **Convert to GGUF** for Ollama deployment
2. **Test inference** with benchmark scripts
3. **Deploy to Ollama** on the homelab cluster
