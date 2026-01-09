# Committee Model Training Container
# Builds training environment for Committee 1.5B model from scratch
# Targets: NVIDIA GPUs (RTX 3090 on Arcanine node)

FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

# Set working directory
WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    vim \
    htop \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies for Committee training
# Core training requirements
RUN pip install --no-cache-dir \
    torch>=2.1.0 \
    transformers>=4.36.0 \
    datasets>=2.14.0 \
    accelerate>=0.25.0 \
    tokenizers>=0.15.0 \
    safetensors>=0.4.0 \
    wandb>=0.16.0 \
    tqdm>=4.66.0 \
    pyyaml>=6.0 \
    numpy>=1.24.0 \
    sentencepiece>=0.1.99 \
    protobuf>=4.25.0 \
    einops>=0.7.0 \
    flash-attn --no-build-isolation

# Copy training code (will be mounted at runtime for development)
# For production, uncomment and build with training code included:
# COPY training/ /workspace/training/
# COPY data/tokenizer/ /workspace/data/tokenizer/

# Environment variables for NVIDIA GPU
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=all
ENV CUDA_DEVICE_ORDER=PCI_BUS_ID

# Default command (override in Kubernetes Job)
CMD ["python", "-c", "import torch; print(f'PyTorch {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"]
