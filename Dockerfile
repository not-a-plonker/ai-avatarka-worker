# Clean slate Dockerfile with proven SageAttention stack
FROM nvidia/cuda:12.8.1-devel-ubuntu22.04

# Consolidated environment variables (matching their setup)
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    CMAKE_BUILD_PARALLEL_LEVEL=8 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

WORKDIR /workspace

# Install Python 3.10 specifically and make it the default (matching their setup)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3.10-distutils python3-pip python3.10-venv \
    curl ffmpeg ninja-build git git-lfs wget aria2 vim libgl1 libglib2.0-0 \
    build-essential gcc cmake pkg-config \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3 \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10 \
    && ln -sf /usr/local/bin/pip /usr/bin/pip \
    && ln -sf /usr/local/bin/pip /usr/bin/pip3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify Python version
RUN python --version && pip --version

# Create and activate virtual environment
RUN python -m venv $VIRTUAL_ENV

# Install exact PyTorch versions that work with SageAttention (from their setup)
RUN pip install --no-cache-dir torch==2.7.0+cu128 --index-url https://download.pytorch.org/whl/cu128 --no-deps && \
    pip install --no-cache-dir torchvision==0.22.0+cu128 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128

# Install essential packages
RUN pip install runpod~=1.7.9 requests websocket-client onnxruntime-gpu triton

# Clone and install ComfyUI
RUN git clone --depth=1 https://github.com/comfyanonymous/ComfyUI.git ComfyUI && \
    cd ComfyUI && \
    pip install -r requirements.txt

# Install ComfyUI custom nodes that we need
RUN cd ComfyUI/custom_nodes && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && \
    pip install -r requirements.txt && \
    cd .. && \
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

# Install SageAttention from source (their proven method)
RUN echo "📦 Installing SageAttention from source..." && \
    git clone https://github.com/thu-ml/SageAttention.git && \
    cd SageAttention && \
    python setup.py install && \
    cd .. && \
    rm -rf SageAttention && \
    echo "✅ SageAttention installed"

# Verify SageAttention installation
RUN python -c "import sageattention; print('✅ SageAttention import successful')" && \
    python -c "import torch; print(f'PyTorch: {torch.__version__}')" && \
    python -c "import triton; print(f'Triton: {triton.__version__}')"

# Create model directories
RUN mkdir -p /workspace/ComfyUI/models/diffusion_models \
             /workspace/ComfyUI/models/vae \
             /workspace/ComfyUI/models/text_encoders \
             /workspace/ComfyUI/models/clip_vision \
             /workspace/ComfyUI/models/loras \
             /workspace/ComfyUI/input \
             /workspace/ComfyUI/output

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

# Copy project files
COPY workflow/ /workspace/workflow/
COPY prompts/ /workspace/prompts/
COPY lora/ /workspace/ComfyUI/models/loras/
COPY src/handler.py /workspace/src/handler.py

# Download LoRA files using gdown (keeping your existing LoRAs)
RUN pip install gdown --no-cache-dir && \
    echo "🎭 Downloading LoRA files from Google Drive..." && \
    \
    echo "Downloading ghostrider.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1fr-o0SOF2Ekqjjv47kXwpbtTyQ4bX67Q" -O /workspace/ComfyUI/models/loras/ghostrider.safetensors && \
    \
    echo "Downloading son_goku.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1DQFMntN2D-7kGm5myeRzFXqW9TdckIen" -O /workspace/ComfyUI/models/loras/son_goku.safetensors && \
    \
    echo "Downloading westworld.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1tK17DuwniI6wrFhPuoeBIb1jIdnn6xZv" -O /workspace/ComfyUI/models/loras/westworld.safetensors && \
    \
    echo "Downloading hulk.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1LC-OF-ytSy9vnAkJft5QfykIW-qakrJg" -O /workspace/ComfyUI/models/loras/hulk.safetensors && \
    \
    echo "Downloading super_saian.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1DdUdskRIFgb5td_DAsrRIJwdrK5DnkMZ" -O /workspace/ComfyUI/models/loras/super_saian.safetensors && \
    \
    echo "Downloading jumpscare.safetensors..." && \
    gdown "https://drive.google.com/uc?id=15oW0m7sudMBpoGGREHjZAtC92k6dspWq" -O /workspace/ComfyUI/models/loras/jumpscare.safetensors && \
    \
    echo "Downloading kamehameha.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1c9GAVuwUYdoodAcU5svvEzHzsJuE19mi" -O /workspace/ComfyUI/models/loras/kamehameha.safetensors && \
    \
    echo "Downloading melt_it.safetensors..." && \
    gdown "https://drive.google.com/uc?id=139fvofiYDVZGGTHDUsBrAbzNLQ0TFKJf" -O /workspace/ComfyUI/models/loras/melt_it.safetensors && \
    \
    echo "Downloading mindblown.safetensors..." && \
    gdown "https://drive.google.com/uc?id=15Q3lQ9U_0TwWgf8pNmovuHB1VOo7js3A" -O /workspace/ComfyUI/models/loras/mindblown.safetensors && \
    \
    echo "Downloading muscles.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1_FxWR_fZnWaI3Etxr19BAfJGUtqLHz88" -O /workspace/ComfyUI/models/loras/muscles.safetensors && \
    \
    echo "Downloading crush_it.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1q_xAeRppHGc3caobmAk4Cpi-3PBJA97i" -O /workspace/ComfyUI/models/loras/crush_it.safetensors && \
    \
    echo "Downloading samurai.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1-N3XS5wpRcI95BJUnRr3PnMp7oCVAF3u" -O /workspace/ComfyUI/models/loras/samurai.safetensors && \
    \
    echo "Downloading fus_ro_dah.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1-ruIAhaVzHPCERvh6cFY-s1b-s5dxmRA" -O /workspace/ComfyUI/models/loras/fus_ro_dah.safetensors && \
    \
    echo "Downloading 360.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1S637vBYR21UKmTM3KI-S2cxrwKu3GDDR" -O /workspace/ComfyUI/models/loras/360.safetensors && \
    \
    echo "Downloading vip_50_epochs.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1NcnSdMO4zew5078T3aQTK9cfxcnoMtjN" -O /workspace/ComfyUI/models/loras/vip_50_epochs.safetensors && \
    \
    echo "Downloading puppy.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1DZokL-bwacMIggimUlj2LAme_f4pOWdv" -O /workspace/ComfyUI/models/loras/puppy.safetensors && \
    \
    echo "Downloading snow_white.safetensors..." && \
    gdown "https://drive.google.com/uc?id=1geUbpu-Q-N4VxM6ncbC2-Y9Tidqbpt8D" -O /workspace/ComfyUI/models/loras/snow_white.safetensors && \
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

# Create startup script that uses our handler with SageAttention
RUN echo '#!/usr/bin/env python3\nimport sys\nsys.path.append("/workspace/src")\nfrom handler import handler\nimport runpod\nprint("🚀 Starting AI-Avatarka handler with SageAttention...")\nrunpod.serverless.start({"handler": handler})' > /workspace/start.py && chmod +x /workspace/start.py

WORKDIR /workspace
CMD ["python", "/workspace/start.py"]