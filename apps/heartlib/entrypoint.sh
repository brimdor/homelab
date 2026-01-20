#!/bin/bash
set -e

MODEL_PATH="${MODEL_PATH:-/models}"
MODELS_READY_FILE="${MODEL_PATH}/.models_ready"

# Function to download models from HuggingFace
download_models() {
    echo "=========================================="
    echo "HeartLib Model Downloader"
    echo "=========================================="
    echo "Model path: ${MODEL_PATH}"
    echo ""

    # Check if models already downloaded
    if [ -f "${MODELS_READY_FILE}" ]; then
        echo "✅ Models already downloaded, skipping..."
        return 0
    fi

    echo "📥 Downloading models from HuggingFace..."
    echo ""

    # Install huggingface_hub if not present
    pip install --quiet huggingface_hub

    # Download HeartMuLaGen (tokenizer and config)
    echo "[1/3] Downloading HeartMuLaGen..."
    python3.10 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='HeartMuLa/HeartMuLaGen',
    local_dir='${MODEL_PATH}',
    local_dir_use_symlinks=False
)
"

    # Download HeartMuLa-oss-3B
    echo "[2/3] Downloading HeartMuLa-oss-3B..."
    python3.10 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='HeartMuLa/HeartMuLa-oss-3B',
    local_dir='${MODEL_PATH}/HeartMuLa-oss-3B',
    local_dir_use_symlinks=False
)
"

    # Download HeartCodec-oss
    echo "[3/3] Downloading HeartCodec-oss..."
    python3.10 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='HeartMuLa/HeartCodec-oss',
    local_dir='${MODEL_PATH}/HeartCodec-oss',
    local_dir_use_symlinks=False
)
"

    # Mark models as ready
    echo "$(date -Iseconds)" > "${MODELS_READY_FILE}"
    echo ""
    echo "✅ All models downloaded successfully!"
}

# Main entrypoint
echo "=========================================="
echo "HeartLib Container Starting"
echo "=========================================="

# Download models if needed
download_models

echo ""
echo "🚀 Starting Gradio web interface..."
echo ""

# Start the Gradio app
exec python3.10 /app/app.py
