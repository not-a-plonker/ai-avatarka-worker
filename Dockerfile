# AI-Avatarka - Keep your existing base image, fix only the specific issues
# TODO: Replace with your actual base image from working setup
FROM hearmeman/comfyui-wan-template:v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH="/workspace/ComfyUI" \
    PYTHONDONTWRITEBYTECODE=1

# Only install what we need for the fixes
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY requirements.txt /workspace/requirements.txt
COPY src/ /workspace/src/
COPY builder/ /workspace/builder/
COPY prompts/ /workspace/prompts/
COPY workflow/ /workspace/workflow/
COPY worker-config.json /workspace/

# CRITICAL FIX: Install dependencies without breaking existing versions
# Your logs showed runtime reinstallation caused conflicts, so we prevent that
RUN echo "🔧 Installing only safe dependencies that don't conflict with base image..." && \
    pip install --no-cache-dir runpod~=1.7.9 gdown>=5.0.0

# Keep existing ComfyUI installation or install if missing
RUN if [ ! -f "/workspace/ComfyUI/main.py" ]; then \
        echo "🔧 Installing ComfyUI..."; \
        cd /workspace && \
        git clone https://github.com/comfyanonymous/ComfyUI.git && \
        cd ComfyUI && \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        echo "✅ ComfyUI already present in base image"; \
    fi

# Create ComfyUI directory structure
RUN mkdir -p /workspace/ComfyUI/models/{diffusion_models,vae,text_encoders,clip_vision,loras,controlnet,upscale_models} \
    /workspace/ComfyUI/{input,output,custom_nodes}

# Install custom nodes
RUN cd /workspace/ComfyUI/custom_nodes && \
    echo "📦 Installing custom nodes..." && \
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    git clone https://github.com/kijai/ComfyUI-KJNodes.git && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git

# Install custom node requirements (skip any sageattention refs)
RUN for dir in /workspace/ComfyUI/custom_nodes/*/; do \
        if [ -f "$dir/requirements.txt" ]; then \
            echo "Installing requirements for $(basename $dir)"; \
            # Remove any sageattention lines to avoid conflicts \
            sed -i '/sageattention/d' "$dir/requirements.txt"; \
            pip install --no-cache-dir -r "$dir/requirements.txt"; \
        fi; \
    done

# Download core Wan 2.1 models
RUN echo "📦 Downloading Wan 2.1 models..." && \
    cd /workspace/ComfyUI/models && \
    \
    echo "Downloading diffusion model..." && \
    wget --progress=dot:giga -O diffusion_models/wan2.1_i2v_480p_14B_bf16.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/diffusion_models/wan2.1_i2v_480p_14B_bf16.safetensors" && \
    \
    echo "Downloading VAE..." && \
    wget --progress=dot:giga -O vae/wan_2.1_vae.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" && \
    \
    echo "Downloading text encoder..." && \
    wget --progress=dot:giga -O text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" && \
    \
    echo "Downloading CLIP vision..." && \
    wget --progress=dot:giga -O clip_vision/clip_vision_h.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors" && \
    \
    echo "✅ Core models downloaded"

# Download LoRA files
RUN echo "🎭 Downloading LoRA files..." && \
    python /workspace/builder/download_models.py && \
    echo "✅ LoRA files downloaded"

# Pre-build SageAttention to avoid runtime compilation issues
RUN echo "🔧 Pre-building SageAttention with Python 3.11 and triton 3.0.0..." && \
    export TORCH_CUDA_ARCH_LIST="8.6;8.9;9.0" && \
    export CUDA_VISIBLE_DEVICES=0 && \
    export MAX_JOBS=4 && \
    export PYTHONDONTWRITEBYTECODE=1 && \
    \
    # Clear any existing cache
    rm -rf ~/.triton /tmp/.triton /root/.triton 2>/dev/null || true && \
    \
    # Create temp build directory
    mkdir -p /tmp/sageattention_build && \
    cd /tmp/sageattention_build && \
    \
    # Clone and build
    git clone --depth 1 https://github.com/thu-ml/SageAttention.git . && \
    python setup.py install && \
    \
    # Verify installation
    python -c "from sageattention import sageattn; print('✅ SageAttention pre-built successfully')" && \
    \
    # Clean up build files
    cd / && rm -rf /tmp/sageattention_build ~/.triton /tmp/.triton /root/.triton

# Verify all installations
RUN echo "🔍 Verifying installations..." && \
    ls -lh /workspace/ComfyUI/models/diffusion_models/ && \
    ls -lh /workspace/ComfyUI/models/vae/ && \
    ls -lh /workspace/ComfyUI/models/text_encoders/ && \
    ls -lh /workspace/ComfyUI/models/clip_vision/ && \
    ls -lh /workspace/ComfyUI/models/loras/ && \
    python -c "import torch; print(f'PyTorch: {torch.__version__}')" && \
    python -c "import triton; print(f'Triton: {triton.__version__}')" && \
    python -c "from sageattention import sageattn; print('SageAttention: OK')" && \
    echo "✅ All verifications passed"

# Clean up build files and caches
RUN rm -rf /workspace/builder/ /tmp/* /var/lib/apt/lists/* ~/.cache/pip \
    ~/.triton /tmp/.triton /root/.triton 2>/dev/null || true

# Create optimized startup script
RUN echo '#!/usr/bin/env python3\n\
import sys\n\
import os\n\
\n\
# Clear any stale triton cache on startup\n\
import shutil\n\
from pathlib import Path\n\
for cache_path in [Path.home() / ".triton", Path("/tmp/.triton"), Path("/root/.triton")]:\n\
    if cache_path.exists():\n\
        try:\n\
            shutil.rmtree(cache_path)\n\
            print(f"Cleared cache: {cache_path}")\n\
        except:\n\
            pass\n\
\n\
sys.path.append("/workspace/src")\n\
from handler import handler\n\
import runpod\n\
\n\
print("🚀 Starting AI-Avatarka handler with SageAttention support...")\n\
print("🔧 SageAttention pre-built and ready")\n\
print("🎯 ComfyUI will start with --use-sage-attention flag")\n\
\n\
runpod.serverless.start({"handler": handler})' > /workspace/start.py && \
    chmod +x /workspace/start.py

# Final environment setup
ENV TORCH_CUDA_ARCH_LIST="8.6;8.9;9.0"
ENV CUDA_VISIBLE_DEVICES=0
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace
CMD ["python", "/workspace/start.py"]