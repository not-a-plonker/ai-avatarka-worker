# AI-Avatarka - Simple debug version 
FROM hearmeman/comfyui-wan-template:v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH="/workspace/ComfyUI"

# STEP 1: Check base image
RUN echo "=== STEP 1: BASE IMAGE CHECK ===" && \
    python --version && \
    pip list | grep -i sage || echo "No sageattention in pip list" && \
    python -c "import sageattention; print('BASE: SageAttention found')" || echo "BASE: SageAttention NOT found" && \
    python -c "from sageattention import sageattn; print('BASE: sageattn import works')" || echo "BASE: sageattn import FAILED"

# Install basic dependencies
RUN pip install --no-cache-dir runpod~=1.7.9 gdown>=5.0.0

# STEP 2: Check after basic deps
RUN echo "=== STEP 2: AFTER BASIC DEPS ===" && \
    python -c "from sageattention import sageattn; print('BASIC DEPS: sageattn still works')" || echo "BASIC DEPS: sageattn BROKEN"

# Install your requirements
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# STEP 3: Check after requirements
RUN echo "=== STEP 3: AFTER REQUIREMENTS ===" && \
    pip list | grep -i sage && \
    python -c "from sageattention import sageattn; print('REQUIREMENTS: sageattn still works')" || echo "REQUIREMENTS: sageattn BROKEN - THIS IS THE CULPRIT!"

# Ensure ComfyUI exists
RUN if [ ! -f "/workspace/ComfyUI/main.py" ]; then \
        echo "Installing ComfyUI..."; \
        mkdir -p /workspace && \
        cd /workspace && \
        git clone https://github.com/comfyanonymous/ComfyUI.git && \
        cd ComfyUI && \
        pip install -r requirements.txt; \
    else \
        echo "ComfyUI already present"; \
    fi

# STEP 4: Check after ComfyUI
RUN echo "=== STEP 4: AFTER COMFYUI ===" && \
    python -c "from sageattention import sageattn; print('COMFYUI: sageattn still works')" || echo "COMFYUI: sageattn BROKEN"

# Install custom nodes
RUN mkdir -p /workspace/ComfyUI/custom_nodes && \
    cd /workspace/ComfyUI/custom_nodes && \
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    git clone https://github.com/cubiq/ComfyUI_essentials.git

# STEP 5: Check after custom nodes clone
RUN echo "=== STEP 5: AFTER CUSTOM NODES CLONE ===" && \
    python -c "from sageattention import sageattn; print('CUSTOM CLONE: sageattn still works')" || echo "CUSTOM CLONE: sageattn BROKEN"

# Install custom node requirements
RUN for dir in /workspace/ComfyUI/custom_nodes/*/; do \
        if [ -f "$dir/requirements.txt" ]; then \
            echo "Installing requirements for $(basename $dir)"; \
            cat "$dir/requirements.txt"; \
            pip install --no-cache-dir -r "$dir/requirements.txt"; \
        fi; \
    done

# STEP 6: Check after custom node requirements
RUN echo "=== STEP 6: AFTER CUSTOM NODE REQUIREMENTS ===" && \
    python -c "from sageattention import sageattn; print('CUSTOM REQS: sageattn still works')" || echo "CUSTOM REQS: sageattn BROKEN - CUSTOM NODE REQUIREMENTS ARE THE CULPRIT!"

# FINAL CHECK
RUN echo "=== FINAL CHECK ===" && \
    pip list | grep -i sage && \
    python -c "from sageattention import sageattn; print('FINAL: Everything works!')" || echo "FINAL: Still broken"

# Create startup script for testing
RUN echo '#!/usr/bin/env python3\nprint("Testing SageAttention at runtime...")\ntry:\n    from sageattention import sageattn\n    print("✅ SageAttention works at runtime!")\nexcept Exception as e:\n    print("❌ SageAttention failed at runtime:", e)' > /workspace/test_sage.py && chmod +x /workspace/test_sage.py

WORKDIR /workspace
CMD ["python", "/workspace/test_sage.py"]