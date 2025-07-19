# AI-Avatarka - Build SageAttention at runtime like hearmeman
FROM hearmeman/comfyui-wan-template:v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH="/workspace/ComfyUI"

# Install build dependencies (needed for runtime SageAttention compilation)
RUN apt-get update && apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies
RUN pip install --no-cache-dir runpod~=1.7.9 gdown>=5.0.0

# Copy and install requirements (EXCLUDING sageattention AND flash-attn)
COPY requirements.txt /tmp/requirements.txt
RUN sed -i '/sageattention/d' /tmp/requirements.txt && \
    sed -i '/flash-attn/d' /tmp/requirements.txt && \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

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

# Install custom node requirements (but skip any that try to reinstall SageAttention)
RUN for dir in /workspace/ComfyUI/custom_nodes/*/; do \
        if [ -f "$dir/requirements.txt" ]; then \
            echo "Installing requirements for $(basename $dir)"; \
            sed -i '/sageattention/d' "$dir/requirements.txt"; \
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

# Download LoRA files using individual gdown commands
RUN echo "🎭 Downloading LoRA files from Google Drive..." && \
    /opt/venv/bin/python -m pip install gdown --no-cache-dir && \
    \
    echo "Downloading ghostrider.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1fr-o0SOF2Ekqjjv47kXwpbtTyQ4bX67Q" -O /workspace/ComfyUI/models/loras/ghostrider.safetensors && \
    \
    echo "Downloading son_goku.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1DQFMntN2D-7kGm5myeRzFXqW9TdckIen" -O /workspace/ComfyUI/models/loras/son_goku.safetensors && \
    \
    echo "Downloading westworld.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1tK17DuwniI6wrFhPuoeBIb1jIdnn6xZv" -O /workspace/ComfyUI/models/loras/westworld.safetensors && \
    \
    echo "Downloading hulk.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1LC-OF-ytSy9vnAkJft5QfykIW-qakrJg" -O /workspace/ComfyUI/models/loras/hulk.safetensors && \
    \
    echo "Downloading super_saian.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1DdUdskRIFgb5td_DAsrRIJwdrK5DnkMZ" -O /workspace/ComfyUI/models/loras/super_saian.safetensors && \
    \
    echo "Downloading jumpscare.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=15oW0m7sudMBpoGGREHjZAtC92k6dspWq" -O /workspace/ComfyUI/models/loras/jumpscare.safetensors && \
    \
    echo "Downloading kamehameha.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1c9GAVuwUYdoodAcU5svvEzHzsJuE19mi" -O /workspace/ComfyUI/models/loras/kamehameha.safetensors && \
    \
    echo "Downloading melt_it.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=139fvofiYDVZGGTHDUsBrAbzNLQ0TFKJf" -O /workspace/ComfyUI/models/loras/melt_it.safetensors && \
    \
    echo "Downloading mindblown.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=15Q3lQ9U_0TwWgf8pNmovuHB1VOo7js3A" -O /workspace/ComfyUI/models/loras/mindblown.safetensors && \
    \
    echo "Downloading muscles.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1_FxWR_fZnWaI3Etxr19BAfJGUtqLHz88" -O /workspace/ComfyUI/models/loras/muscles.safetensors && \
    \
    echo "Downloading crush_it.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1q_xAeRppHGc3caobmAk4Cpi-3PBJA97i" -O /workspace/ComfyUI/models/loras/crush_it.safetensors && \
    \
    echo "Downloading samurai.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1-N3XS5wpRcI95BJUnRr3PnMp7oCVAF3u" -O /workspace/ComfyUI/models/loras/samurai.safetensors && \
    \
    echo "Downloading fus_ro_dah.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1-ruIAhaVzHPCERvh6cFY-s1b-s5dxmRA" -O /workspace/ComfyUI/models/loras/fus_ro_dah.safetensors && \
    \
    echo "Downloading 360.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1S637vBYR21UKmTM3KI-S2cxrwKu3GDDR" -O /workspace/ComfyUI/models/loras/360.safetensors && \
    \
    echo "Downloading vip_50_epochs.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1NcnSdMO4zew5078T3aQTK9cfxcnoMtjN" -O /workspace/ComfyUI/models/loras/vip_50_epochs.safetensors && \
    \
    echo "Downloading puppy.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1DZokL-bwacMIggimUlj2LAme_f4pOWdv" -O /workspace/ComfyUI/models/loras/puppy.safetensors && \
    \
    echo "Downloading snow_white.safetensors..." && \
    /opt/venv/bin/python -m gdown "https://drive.google.com/uc?id=1geUbpu-Q-N4VxM6ncbC2-Y9Tidqbpt8D" -O /workspace/ComfyUI/models/loras/snow_white.safetensors && \
    \
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
    echo "✅ All models and LoRAs downloaded during build!"

# Clean up build files to reduce image size
RUN rm -rf /tmp/* /var/lib/apt/lists/*

# Create startup script that uses our new handler
RUN echo '#!/usr/bin/env python3\nimport sys\nsys.path.append("/workspace/src")\nfrom handler import handler\nimport runpod\nprint("🚀 Starting AI-Avatarka handler...")\nrunpod.serverless.start({"handler": handler})' > /workspace/start.py && chmod +x /workspace/start.py

WORKDIR /workspace
CMD ["python", "/workspace/start.py"]