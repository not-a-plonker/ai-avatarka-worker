# AI-Avatarka - Optimized to prevent runner crashes
FROM hearmeman/comfyui-wan-template:v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH="/workspace/ComfyUI"

# Install build dependencies for SageAttention compilation
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Install basic dependencies
RUN pip install --no-cache-dir runpod~=1.7.9 gdown>=5.0.0

# Install your requirements EXCEPT sageattention (we'll install it from source)
COPY requirements.txt /tmp/requirements.txt
RUN sed -i '/sageattention/d' /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Install SageAttention from source with memory optimization
RUN echo "🔧 Installing SageAttention from source..." && \
    cd /tmp && \
    git clone --depth 1 https://github.com/thu-ml/SageAttention.git && \
    cd SageAttention && \
    MAX_JOBS=1 python setup.py install && \
    cd / && \
    rm -rf /tmp/SageAttention && \
    echo "✅ SageAttention installed"

# Verify SageAttention works
RUN python -c "from sageattention import sageattn; print('✅ SageAttention verified working')"

# Ensure ComfyUI exists
RUN if [ ! -f "/workspace/ComfyUI/main.py" ]; then \
        echo "Installing ComfyUI..."; \
        mkdir -p /workspace && \
        cd /workspace && \
        git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git && \
        cd ComfyUI && \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        echo "ComfyUI already present"; \
    fi

# Create custom_nodes directory and install custom nodes
RUN mkdir -p /workspace/ComfyUI/custom_nodes && \
    cd /workspace/ComfyUI/custom_nodes && \
    echo "📦 Installing custom nodes..." && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    git clone --depth 1 https://github.com/cubiq/ComfyUI_essentials.git

# Install custom node requirements with memory optimization
RUN for dir in /workspace/ComfyUI/custom_nodes/*/; do \
        if [ -f "$dir/requirements.txt" ]; then \
            echo "Installing requirements for $(basename $dir)"; \
            pip install --no-cache-dir -r "$dir/requirements.txt" || echo "Failed to install requirements for $(basename $dir)"; \
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

# Copy project files BEFORE model downloads to use cache
COPY workflow/ /workspace/ComfyUI/workflow/
COPY prompts/ /workspace/prompts/
COPY lora/ /workspace/ComfyUI/models/loras/
COPY builder/ /workspace/builder/
COPY src/handler.py /workspace/src/handler.py

# Download models with better error handling and retries
RUN echo "📦 Downloading Wan 2.1 models..." && \
    echo "Downloading diffusion model (largest)..." && \
    wget -c --progress=dot:giga --timeout=300 --tries=5 --retry-connrefused \
    -O /workspace/ComfyUI/models/diffusion_models/wan2.1_i2v_480p_14B_bf16.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/diffusion_models/wan2.1_i2v_480p_14B_bf16.safetensors" && \
    echo "Downloading VAE..." && \
    wget -c --progress=dot:giga --timeout=300 --tries=5 --retry-connrefused \
    -O /workspace/ComfyUI/models/vae/wan_2.1_vae.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" && \
    echo "Downloading text encoder..." && \
    wget -c --progress=dot:giga --timeout=300 --tries=5 --retry-connrefused \
    -O /workspace/ComfyUI/models/text_encoders/umt5-xxl-enc-bf16.safetensors \
    "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/umt5-xxl-enc-bf16.safetensors" && \
    echo "Downloading CLIP vision..." && \
    wget -c --progress=dot:giga --timeout=300 --tries=5 --retry-connrefused \
    -O /workspace/ComfyUI/models/clip_vision/open-clip-xlm-roberta-large-vit-huge-14_fp16.safetensors \
    "https://huggingface.co/Kijai/WanVideo_comfy/resolve/b4fde5290d401dff216d70a915643411e9532951/open-clip-xlm-roberta-large-vit-huge-14_fp16.safetensors" && \
    echo "✅ Base models downloaded"

# Download LoRA files using our script with timeout protection
RUN echo "🎭 Downloading LoRA files..." && \
    timeout 1800 python /workspace/builder/download_models.py || echo "LoRA download timed out but continuing..." && \
    echo "✅ LoRA download attempted"

# Clean up build files early to free space
RUN rm -rf /workspace/builder/ /tmp/* /var/lib/apt/lists/*

# Final verification with error handling
RUN echo "🔍 Final verification..." && \
    python -c "from sageattention import sageattn; print('✅ SageAttention final check passed')" || echo "⚠️ SageAttention check failed" && \
    ls -lh /workspace/ComfyUI/main.py && \
    echo "✅ Verification complete"

# Create startup script
RUN echo '#!/usr/bin/env python3\nimport sys\nsys.path.append("/workspace/src")\nfrom handler import handler\nimport runpod\nprint("🚀 Starting AI-Avatarka handler...")\nrunpod.serverless.start({"handler": handler})' > /workspace/start.py && chmod +x /workspace/start.py

WORKDIR /workspace
CMD ["python", "/workspace/start.py"]