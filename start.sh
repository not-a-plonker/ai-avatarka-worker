#!/usr/bin/env bash

# Check if /runpod-volume exists (following runpod-wan pattern)
if [ -d "/runpod-volume" ]; then
  echo "🔗 Symlinking files from Network Volume"
  rm -rf /workspace && ln -s /runpod-volume /workspace
  
  # Copy project files to network storage if they don't exist
  if [ ! -d "/workspace/workflow" ]; then
    echo "📁 Copying workflow files to network storage..."
    cp -r /tmp/workflow /workspace/
  fi
  if [ ! -d "/workspace/prompts" ]; then
    echo "📁 Copying prompts files to network storage..."
    cp -r /tmp/prompts /workspace/
  fi
  
  echo "🔧 Activating virtual environment..."
  source /workspace/venv/bin/activate
  echo "📍 venv info:"
  echo $VIRTUAL_ENV && python -V && which python && which pip
  
  # Use libtcmalloc for better memory management (from runpod-wan)
  TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
  export LD_PRELOAD="${TCMALLOC}"
  export PYTHONUNBUFFERED=true
  export HF_HOME="/workspace"
  
  # Set ComfyUI-Manager to offline mode to prevent registry fetching
  export COMFYUI_MANAGER_OFFLINE=1
  export DISABLE_COMFYUI_MANAGER_NETWORK=1
  
  # Check ComfyUI structure (you renamed comfywan to ComfyUI)
  if [ -d "/workspace/ComfyUI" ]; then
    COMFYUI_DIR="/workspace/ComfyUI"
    echo "✅ Found ComfyUI at /workspace/ComfyUI"
  elif [ -d "/workspace/comfywan" ]; then
    COMFYUI_DIR="/workspace/comfywan"
    echo "✅ Found ComfyUI at /workspace/comfywan"
  else
    echo "❌ ComfyUI not found in /workspace/ComfyUI or /workspace/comfywan"
    exit 1
  fi
  
  cd $COMFYUI_DIR
  
  # Set ComfyUI-Manager to offline mode (following runpod-wan pattern)
  comfy-manager-set-mode offline || echo "⚠️ Could not set ComfyUI-Manager network_mode (script not found)" >&2
  
  echo "🚀 Starting ComfyUI in offline mode (no registry fetching)"
  # Allow operators to tweak verbosity; default is INFO.
  : "${COMFY_LOG_LEVEL:=INFO}"

  # Start ComfyUI in background (offline mode set above)
  python -u $COMFYUI_DIR/main.py --port 8188 --use-sage-attention --base-directory $COMFYUI_DIR --disable-auto-launch --disable-metadata --verbose "${COMFY_LOG_LEVEL}" --log-stdout &
  
  # Wait a moment for ComfyUI to start
  sleep 5
  
  echo "🎯 Starting RunPod Handler"
  # Export ComfyUI path for handler
  export COMFYUI_PATH=$COMFYUI_DIR
  exec python -u /rp_handler.py
else
  echo "❌ Warning: /runpod-volume does not exist"
  exit 1
fi
