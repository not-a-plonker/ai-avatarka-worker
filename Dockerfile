# AI-Avatarka - Fixed git clone issues with hearmeman base
FROM hearmeman/comfyui-wan-template:v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH="/workspace/ComfyUI"

# Install ONLY RunPod serverless and gdown - DON'T TOUCH BASE IMAGE DEPENDENCIES
RUN pip install --no-cache-dir runpod~=1.7.9 gdown>=5.0.0

# Copy project files
COPY src/handler.py /workspace/src/handler.py
COPY builder/ /workspace/builder/
COPY prompts/ /workspace/prompts/
COPY workflow/ /workspace/workflow/
COPY worker-config.json /workspace/

# Debug: Check what's actually in hearmeman's base image
RUN echo "🔍 DEBUGGING hearmeman's base image structure..." && \
    echo "=== Root directory ===" && \
    ls -la / | head -20 && \
    echo "=== Workspace directory ===" && \
    ls -la /workspace/ 2>/dev/null || echo "No /workspace directory" && \
    echo "=== Looking for ComfyUI ===" && \
    find / -name "ComfyUI" -type d 2>/dev/null | head -5 && \
    echo "=== ComfyUI contents (if exists) ===" && \
    ls -la /ComfyUI/ 2>/dev/null || echo "No /ComfyUI directory" && \
    ls -la /workspace/ComfyUI/ 2>/dev/null || echo "No /workspace/ComfyUI directory"

# Debug: Check ComfyUI structure before downloading models
RUN echo "🔍 Checking ComfyUI structure before model downloads..." && \
    ls -la /workspace/ComfyUI/ && \
    echo "=== Models directory ===" && \
    ls -la /workspace/ComfyUI/models/ 2>/dev/null || echo "No models directory" && \
    echo "=== Creating missing model dirs ===" && \
    mkdir -p /workspace/ComfyUI/models/diffusion_models \
             /workspace/ComfyUI/models/vae \
             /workspace/ComfyUI/models/text_encoders \
             /workspace/ComfyUI/models/clip_vision \
             /workspace/ComfyUI/models/loras && \
    echo "=== After mkdir ===" && \
    ls -la /workspace/ComfyUI/models/

# Copy our workflow
RUN cp /workspace/workflow/* /workspace/ComfyUI/workflow/ 2>/dev/null || echo "No workflow files"

# Install custom nodes with proper error handling
RUN echo "📦 Installing custom nodes with error handling..." && \
    cd /workspace/ComfyUI/custom_nodes && \
    pwd && \
    ls -la . && \
    echo "Cloning WanVideoWrapper..." && \
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git || echo "Failed to clone WanVideoWrapper" && \
    echo "Cloning VideoHelperSuite..." && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git || echo "Failed to clone VideoHelperSuite" && \
    echo "Cloning essentials..." && \
    git clone https://github.com/cubiq/ComfyUI_essentials.git || echo "Failed to clone essentials" && \
    echo "Custom nodes clone attempts completed" && \
    ls -la .

# Install custom node requirements (safe version)
RUN echo "📋 Installing custom node requirements..." && \
    for dir in /workspace/ComfyUI/custom_nodes/*/; do \
        if [ -d "$dir" ] && [ -f "$dir/requirements.txt" ]; then \
            echo "Processing requirements for $(basename $dir)"; \
            cp "$dir/requirements.txt" "$dir/requirements.txt.backup"; \
            sed -i '/sageattention/d; /torch/d; /triton/d; /xformers/d; /numpy/d; /scipy/d' "$dir/requirements.txt"; \
            if [ -s "$dir/requirements.txt" ]; then \
                pip install --no-cache-dir -r "$dir/requirements.txt" || echo "Failed to install requirements for $(basename $dir)"; \
            else \
                echo "No safe requirements left for $(basename $dir)"; \
            fi; \
        fi; \
    done

# Download models during build - YOUR EXACT WORKING COMMANDS
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

# Download LoRA files
RUN echo "🎭 Downloading LoRA files..." && \
    python /workspace/builder/download_models.py && \
    echo "✅ LoRA files downloaded"

# Final verification
RUN echo "🔍 Final verification..." && \
    ls -lh /workspace/ComfyUI/models/diffusion_models/ && \
    ls -lh /workspace/ComfyUI/models/vae/ && \
    ls -lh /workspace/ComfyUI/models/text_encoders/ && \
    ls -lh /workspace/ComfyUI/models/clip_vision/ && \
    ls -lh /workspace/ComfyUI/models/loras/ && \
    ls -la /workspace/ComfyUI/custom_nodes/ && \
    echo "✅ All verified!"

# Clean up
RUN rm -rf /workspace/builder/ /tmp/* /var/lib/apt/lists/*

# Create startup script
RUN echo '#!/usr/bin/env python3\n\
import sys\n\
sys.path.append("/workspace/src")\n\
from handler import handler\n\
import runpod\n\
print("🚀 Starting AI-Avatarka handler...")\n\
runpod.serverless.start({"handler": handler})' > /workspace/start.py && \
    chmod +x /workspace/start.py

WORKDIR /workspace
CMD ["python", "/workspace/start.py"]