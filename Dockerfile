# AI-Avatarka - Build SageAttention at runtime like hearmeman
FROM hearmeman/comfyui-wan-template:v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH="/workspace/ComfyUI"

# Install ONLY RunPod serverless and gdown - DON'T TOUCH BASE IMAGE DEPENDENCIES
RUN pip install --no-cache-dir --no-deps runpod~=1.7.9 gdown>=5.0.0

# DON'T install requirements.txt - causes conflicts with base image
# The base image already has torch, triton, xformers, etc.

# Debug: Check what's in the base image
RUN echo "🔍 Checking base image contents..." && \
    ls -la /workspace/ || echo "No /workspace directory" && \
    find / -name "ComfyUI" -type d 2>/dev/null || echo "No ComfyUI directory found"

# Ensure ComfyUI is properly installed
RUN if [ ! -f "/workspace/ComfyUI/main.py" ]; then \
        echo "🔧 Installing ComfyUI..."; \
        mkdir -p /workspace && \
        cd /workspace && \
        git clone https://github.com/comfyanonymous/ComfyUI.git && \
        cd ComfyUI && \
        pip install -r requirements.txt; \
    else \
        echo "✅ ComfyUI already present"; \
    fi

# Verify ComfyUI installation
RUN echo "🔍 Verifying ComfyUI installation..." && \
    ls -la /workspace/ComfyUI/main.py && \
    echo "✅ ComfyUI main.py found"

# Create custom_nodes directory and install custom nodes
RUN mkdir -p /workspace/ComfyUI/custom_nodes && \
    cd /workspace/ComfyUI/custom_nodes && \
    echo "📦 Installing custom nodes..." && \
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    git clone https://github.com/cubiq/ComfyUI_essentials.git

# Install custom node requirements but AVOID conflicts with base image
RUN for dir in /workspace/ComfyUI/custom_nodes/*/; do \
        if [ -f "$dir/requirements.txt" ]; then \
            echo "Installing requirements for $(basename $dir)"; \
            # Remove ALL potential conflicting packages \
            sed -i '/sageattention/d; /torch/d; /triton/d; /xformers/d; /numpy/d; /scipy/d' "$dir/requirements.txt"; \
            # Only install if there are still requirements left \
            if [ -s "$dir/requirements.txt" ]; then \
                pip install --no-cache-dir -r "$dir/requirements.txt"; \
            fi; \
        fi; \
    done

# Create model directories
RUN mkdir -p /workspace/ComfyUI/models/diffusion_models \
             /workspace/ComfyUI/models/vae \
             /workspace/ComfyUI/models/text_encoders \
             /workspace/ComfyUI/models/clip_vision \
             /workspace/ComfyUI/models/loras \
             /workspace/ComfyUI/input \
             /workspace/ComfyUI/output

# Copy project files
COPY workflow/ /workspace/ComfyUI/workflow/
COPY prompts/ /workspace/prompts/
COPY lora/ /workspace/ComfyUI/models/loras/
COPY builder/ /workspace/builder/
COPY src/handler.py /workspace/src/handler.py

# Download all models during build (using wget for reliability) - EXACT COPY
RUN echo "📦 Downloading Wan 2.1 models..." && \
    wget --progress=dot:giga --timeout=0 --tries=3 \
    -O /workspace/ComfyUI/models/diffusion_models/wan2.1_i2v_480p_14B_bf16.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/diffusion_models/wan2.1_i2v_480p_14B_bf16.safetensors" && \
    \
    wget --progress=dot:giga --timeout=0 --tries=3 \
    -O /workspace/ComfyUI/models/vae/wan_2.1_vae.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" && \
    \
    wget --progress=dot:giga --timeout=0 --tries=3 \
    -O /workspace/ComfyUI/models/text_encoders/umt5-xxl-enc-bf16.safetensors \
    "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/umt5-xxl-enc-bf16.safetensors" && \
    \
    wget --progress=dot:giga --timeout=0 --tries=3 \
    -O /workspace/ComfyUI/models/clip_vision/open-clip-xlm-roberta-large-vit-huge-14_fp16.safetensors \
    "https://huggingface.co/Kijai/WanVideo_comfy/resolve/b4fde5290d401dff216d70a915643411e9532951/open-clip-xlm-roberta-large-vit-huge-14_fp16.safetensors" && \
    \
    echo "✅ Base models downloaded"

# Download LoRA files using our script - EXACT COPY
RUN echo "🎭 Downloading LoRA files..." && \
    python /workspace/builder/download_models.py && \
    echo "✅ LoRA files downloaded"

# Final verification (no SageAttention verification - will be built at runtime) - EXACT COPY
RUN echo "🔍 Final verification..." && \
    echo "ComfyUI main.py:" && ls -lh /workspace/ComfyUI/main.py && \
    echo "Models:" && \
    ls -lh /workspace/ComfyUI/models/diffusion_models/ && \
    ls -lh /workspace/ComfyUI/models/vae/ && \
    ls -lh /workspace/ComfyUI/models/text_encoders/ && \
    ls -lh /workspace/ComfyUI/models/clip_vision/ && \
    echo "LoRA files:" && ls -lh /workspace/ComfyUI/models/loras/ && \
    echo "Custom nodes:" && ls -la /workspace/ComfyUI/custom_nodes/ && \
    echo "✅ All verified and ready! (SageAttention will be built at runtime)"

# Clean up build files to reduce image size - EXACT COPY
RUN rm -rf /workspace/builder/ /tmp/* /var/lib/apt/lists/*

# Create startup script that uses our new handler - EXACT COPY
RUN echo '#!/usr/bin/env python3\nimport sys\nsys.path.append("/workspace/src")\nfrom handler import handler\nimport runpod\nprint("🚀 Starting AI-Avatarka handler...")\nrunpod.serverless.start({"handler": handler})' > /workspace/start.py && chmod +x /workspace/start.py

WORKDIR /workspace
CMD ["python", "/workspace/start.py"]

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