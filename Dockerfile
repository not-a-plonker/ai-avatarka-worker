# AI-Avatarka - Debug version to find the SageAttention issue
FROM hearmeman/comfyui-wan-template:v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH="/workspace/ComfyUI"

# STEP 1: Check what hearmeman's base image actually has
RUN echo "🔍 DEBUGGING: What's in hearmeman's base image?" && \
    echo "Python version:" && python --version && \
    echo "Pip list (looking for sageattention):" && pip list | grep -i sage || echo "No sageattention found in pip list" && \
    echo "Trying to import sageattention from base image:" && \
    python -c "import sys; exec('try:\\n    from sageattention import sageattn\\n    print(\\\"✅ SageAttention import successful from base image\\\")\\nexcept ImportError as e:\\n    print(\\\"❌ SageAttention import failed from base image:\\\", str(e))\\nexcept Exception as e:\\n    print(\\\"❌ Other error:\\\", str(e))')" && \
    echo "Python path:" && python -c "import sys; print('\\n'.join(sys.path))" && \
    echo "Looking for sageattention files:" && \
    find /usr/local/lib/python*/site-packages/ -name "*sage*" 2>/dev/null || echo "No sageattention files found"

# Install dependencies
RUN pip install --no-cache-dir runpod~=1.7.9 gdown>=5.0.0

# STEP 2: Check after installing basic deps
RUN echo "🔍 DEBUGGING: After installing runpod/gdown..." && \
    python -c "exec('try:\\n    from sageattention import sageattn\\n    print(\\\"✅ SageAttention still works after basic deps\\\")\\nexcept ImportError as e:\\n    print(\\\"❌ SageAttention broken after basic deps:\\\", str(e))')"

# Copy and install requirements 
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# STEP 3: Check after installing your requirements
RUN echo "🔍 DEBUGGING: After installing requirements.txt..." && \
    pip list | grep -i sage && \
    python -c "exec('try:\\n    from sageattention import sageattn\\n    print(\\\"✅ SageAttention works after requirements.txt\\\")\\nexcept ImportError as e:\\n    print(\\\"❌ SageAttention BROKEN after requirements.txt:\\\", str(e))\\n    print(\\\"This is likely the culprit!\\\")\\nexcept Exception as e:\\n    print(\\\"❌ Other error:\\\", str(e))')"

# STEP 4: Check what version we have now
RUN echo "🔍 DEBUGGING: SageAttention version info..." && \
    python -c "exec('try:\\n    import sageattention\\n    print(\\\"SageAttention available:\\\", hasattr(sageattention, \\\"sageattn\\\"))\\n    from sageattention import sageattn\\n    print(\\\"✅ sageattn import works\\\")\\nexcept Exception as e:\\n    print(\\\"Error:\\\", e)')"

# Continue with the rest of your build...
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

# STEP 5: Check after ComfyUI installation
RUN echo "🔍 DEBUGGING: After ComfyUI setup..." && \
    python -c "
try:
    from sageattention import sageattn
    print('✅ SageAttention works after ComfyUI setup')
except ImportError as e:
    print('❌ SageAttention broken after ComfyUI setup:', str(e))
"

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

# STEP 6: Check after custom nodes
RUN echo "🔍 DEBUGGING: After custom nodes..." && \
    python -c "exec('try:\\n    from sageattention import sageattn\\n    print(\\\"✅ SageAttention works after custom nodes\\\")\\nexcept ImportError as e:\\n    print(\\\"❌ SageAttention broken after custom nodes:\\\", str(e))\\n    print(\\\"One of the custom nodes broke it!\\\")')"

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

# Skip model downloads for now to focus on SageAttention issue
# RUN echo "📦 Downloading Wan 2.1 models..." && \
#     ... (comment out for debugging)

# FINAL TEST: Try to actually use SageAttention like the WanVideoWrapper would
RUN echo "🔍 FINAL DEBUGGING: Testing actual SageAttention usage..." && \
    python -c "exec('try:\\n    from sageattention import sageattn\\n    print(\\\"✅ SageAttention import successful\\\")\\n    print(\\\"✅ SageAttention ready for use\\\")\\nexcept Exception as e:\\n    print(\\\"❌ FINAL TEST FAILED:\\\", str(e))')"

# Create startup script
RUN echo '#!/usr/bin/env python3\nimport sys\nsys.path.append("/workspace/src")\nfrom handler import handler\nimport runpod\nprint("🚀 Starting AI-Avatarka handler...")\nrunpod.serverless.start({"handler": handler})' > /workspace/start.py && chmod +x /workspace/start.py

WORKDIR /workspace
CMD ["python", "/workspace/start.py"]