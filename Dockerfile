# AI-Avatarka - Complete fixed version with ComfyUI installation
FROM hearmeman/comfyui-wan-template:v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH="/workspace/ComfyUI"

# Install dependencies
RUN pip install --no-cache-dir runpod~=1.7.9 gdown>=5.0.0

# Copy and install requirements (EXCLUDING sageattention AND flash-attn)
COPY requirements.txt /tmp/requirements.txt
RUN sed -i '/sageattention/d' /tmp/requirements.txt && \
    sed -i '/flash-attn/d' /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Install build dependencies
RUN apt-get update && apt-get install -y git build-essential ninja-build

# Clone SageAttention repo
RUN echo "🔧 Cloning SageAttention..." && \
    cd /tmp && \
    git clone https://github.com/thu-ml/SageAttention.git && \
    ls -la SageAttention/

# Compile SageAttention with error capture
RUN echo "📦 Starting SageAttention compilation..." && \
    cd /tmp/SageAttention && \
    python setup.py install --verbose 2>&1 | tee /tmp/sageattention_build.log || \
    (echo "❌ SageAttention compilation failed. Build log:" && cat /tmp/sageattention_build.log && exit 1)

# Clean up
RUN rm -rf /tmp/SageAttention && \
    apt-get remove -y build-essential ninja-build && \
    apt-get autoremove -y

# Verify SageAttention works with detailed debugging
RUN echo "🔍 Debugging SageAttention installation..." && \
    python -c "import sys; print('Python path:', sys.path)" && \
    python -c "import sageattention; print('✅ sageattention module imported'); print('Location:', sageattention.__file__)" || echo "❌ sageattention import failed" && \
    python -c "from sageattention import sageattn; print('✅ sageattn imported successfully')" || echo "❌ sageattn import failed"

# Verify SageAttention works
RUN python -c "from sageattention import sageattn; print('✅ SageAttention verified working')"

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

# Install custom node requirements
RUN for dir in /workspace/ComfyUI/custom_nodes/*/; do \
        if [ -f "$dir/requirements.txt" ]; then \
            echo "Installing requirements for $(basename $dir)"; \
            pip install --no-cache-dir -r "$dir/requirements.txt"; \
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

# Download all models during build (using wget for reliability)
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

# Download LoRA files using our script
RUN echo "🎭 Downloading LoRA files..." && \
    python /workspace/builder/download_models.py && \
    echo "✅ LoRA files downloaded"

# Final verification
RUN echo "🔍 Final verification..." && \
    echo "ComfyUI main.py:" && ls -lh /workspace/ComfyUI/main.py && \
    echo "Models:" && \
    ls -lh /workspace/ComfyUI/models/diffusion_models/ && \
    ls -lh /workspace/ComfyUI/models/vae/ && \
    ls -lh /workspace/ComfyUI/models/text_encoders/ && \
    ls -lh /workspace/ComfyUI/models/clip_vision/ && \
    echo "LoRA files:" && ls -lh /workspace/ComfyUI/models/loras/ && \
    echo "Custom nodes:" && ls -la /workspace/ComfyUI/custom_nodes/ && \
    echo "✅ All verified and ready!"

# Clean up build files to reduce image size
RUN rm -rf /workspace/builder/ /tmp/* /var/lib/apt/lists/*

# Create startup script
RUN echo '#!/usr/bin/env python3\nimport sys\nsys.path.append("/workspace/src")\nfrom handler import handler\nimport runpod\nprint("🚀 Starting AI-Avatarka handler...")\nrunpod.serverless.start({"handler": handler})' > /workspace/start.py && chmod +x /workspace/start.py

WORKDIR /workspace
CMD ["python", "/workspace/start.py"]