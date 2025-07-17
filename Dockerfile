# AI-Avatarka - Diagnostic version to check memory usage
FROM hearmeman/comfyui-wan-template:v2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH="/workspace/ComfyUI"

# Check available resources
RUN echo "🔍 SYSTEM DIAGNOSTICS:" && \
    echo "CPU cores: $(nproc)" && \
    echo "Total RAM: $(free -h | grep Mem | awk '{print $2}')" && \
    echo "Available RAM: $(free -h | grep Mem | awk '{print $7}')" && \
    echo "Disk space: $(df -h / | tail -1 | awk '{print $2, $3, $4}')" && \
    echo "Swap: $(free -h | grep Swap | awk '{print $2}')" && \
    cat /proc/meminfo | grep -E "MemTotal|MemAvailable|SwapTotal"

# Install dependencies with memory monitoring
RUN pip install --no-cache-dir runpod~=1.7.9 gdown>=5.0.0

# Install your requirements EXCEPT the memory-heavy ones
COPY requirements.txt /tmp/requirements.txt
RUN sed -i '/sageattention/d' /tmp/requirements.txt && \
    sed -i '/flash-attn/d' /tmp/requirements.txt && \
    echo "Installing base requirements..." && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt && \
    echo "Memory after base requirements:" && \
    free -h

# Install build tools
RUN apt-get update && apt-get install -y \
    git build-essential ninja-build htop && \
    rm -rf /var/lib/apt/lists/*

# Try SageAttention with constrained memory
RUN echo "🔧 Installing SageAttention with memory constraints..." && \
    echo "Memory before SageAttention:" && free -h && \
    cd /tmp && \
    git clone --depth 1 https://github.com/thu-ml/SageAttention.git && \
    cd SageAttention && \
    echo "Starting SageAttention compilation with MAX_JOBS=1..." && \
    MAX_JOBS=1 MAKEFLAGS="-j1" python setup.py install && \
    cd / && rm -rf /tmp/SageAttention && \
    echo "Memory after SageAttention:" && free -h && \
    python -c "from sageattention import sageattn; print('✅ SageAttention OK')"

# Try FlashAttention with even more constraints
RUN echo "⚡ Attempting FlashAttention with heavy constraints..." && \
    echo "Memory before FlashAttention:" && free -h && \
    echo "Setting strict memory limits..." && \
    ulimit -v 20971520 && \
    MAX_JOBS=1 MAKEFLAGS="-j1" pip install --no-cache-dir flash-attn>=2.0.0 --no-build-isolation --verbose && \
    echo "Memory after FlashAttention:" && free -h && \
    python -c "import flash_attn; print('✅ FlashAttention OK')" || \
    echo "❌ FlashAttention failed but continuing..."

# Check final state
RUN echo "🔍 FINAL DIAGNOSTICS:" && \
    echo "Final memory state:" && free -h && \
    echo "Installed packages:" && \
    pip list | grep -E "(torch|flash|sage|triton)" && \
    echo "Python imports test:" && \
    python -c "
try:
    from sageattention import sageattn
    print('✅ SageAttention: OK')
except Exception as e:
    print('❌ SageAttention:', e)

try:
    import flash_attn
    print('✅ FlashAttention: OK')
except Exception as e:
    print('❌ FlashAttention:', e)

try:
    import torch
    print('✅ PyTorch:', torch.__version__)
except Exception as e:
    print('❌ PyTorch:', e)
"

# Minimal setup to test
RUN mkdir -p /workspace && \
    echo 'print("Basic test complete")' > /workspace/test.py

WORKDIR /workspace
CMD ["python", "test.py"]