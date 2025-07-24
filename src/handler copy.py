"""
AI-Avatarka RunPod Serverless Worker Handler
Updated for Network Storage Setup
"""

import runpod
import json
import os
import sys
import subprocess
import base64
import io
import time
import uuid
import logging
import requests
import shutil
from pathlib import Path
from PIL import Image
from typing import Dict, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Network storage paths - get from environment or detect automatically
NETWORK_STORAGE_BASE = "/workspace"
NETWORK_STORAGE_VENV = "/workspace/venv"
# ComfyUI path will be detected (could be comfywan or ComfyUI)
NETWORK_STORAGE_COMFYUI = os.environ.get("COMFYUI_PATH", "/workspace/ComfyUI")

# Runtime paths (will be set after validation)
COMFYUI_PATH = None
COMFYUI_SERVER = "127.0.0.1:8188"
EFFECTS_CONFIG = "/prompts/effects.json"  # Files copied to network storage root
WORKFLOW_PATH = "/workflow/universal_i2v.json"  # Files copied to network storage rootYUI = os.environ.get("NETWORK_STORAGE_COMFYUI", "/workspace/ComfyUI")

# Runtime paths (will be set after validation)
COMFYUI_PATH = None
COMFYUI_SERVER = "127.0.0.1:8188"
EFFECTS_CONFIG = "/workspace/prompts/effects.json"
WORKFLOW_PATH = "/workspace/workflow/universal_i2v.json"

# Global state
comfyui_process = None
comfyui_initialized = False
effects_data = None
sage_attention_available = False
environment_validated = False

def validate_network_storage():
    """Validate that network storage setup is complete"""
    global COMFYUI_PATH, environment_validated
    
    if environment_validated:
        return True
    
    try:
        logger.info("🔍 Validating network storage setup...")
        
        # Check virtual environment
        venv_python = Path(NETWORK_STORAGE_VENV) / "bin" / "python"
        if not venv_python.exists():
            logger.error(f"❌ Virtual environment not found: {venv_python}")
            return False
        
        # Check ComfyUI installation
        comfyui_main = Path(NETWORK_STORAGE_COMFYUI) / "main.py"
        if not comfyui_main.exists():
            logger.error(f"❌ ComfyUI not found: {comfyui_main}")
            return False
        
        # Check custom nodes
        custom_nodes_dir = Path(NETWORK_STORAGE_COMFYUI) / "custom_nodes"
        if not custom_nodes_dir.exists():
            logger.error(f"❌ Custom nodes directory not found: {custom_nodes_dir}")
            return False
        
        # Check for key custom nodes
        required_nodes = [
            "ComfyUI-Manager",
            "ComfyUI-KJNodes", 
            "ComfyUI-TeaCache"
        ]
        
        for node in required_nodes:
            node_path = custom_nodes_dir / node
            if not node_path.exists():
                logger.warning(f"⚠️ Custom node not found: {node}")
        
        # Check models directory structure
        models_dir = Path(NETWORK_STORAGE_COMFYUI) / "models"
        required_model_dirs = ["diffusion_models", "vae", "text_encoders", "clip_vision", "loras"]
        
        for model_dir in required_model_dirs:
            model_path = models_dir / model_dir
            if not model_path.exists():
                logger.warning(f"⚠️ Model directory not found: {model_path}")
        
        # Set global paths
        COMFYUI_PATH = str(NETWORK_STORAGE_COMFYUI)
        environment_validated = True
        
        logger.info("✅ Network storage validation complete")
        logger.info(f"📁 ComfyUI path: {COMFYUI_PATH}")
        logger.info(f"🐍 Python path: {venv_python}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Network storage validation failed: {e}")
        return False

def activate_network_storage_environment():
    """Activate the network storage virtual environment"""
    try:
        logger.info("🔧 Activating network storage environment...")
        
        # Set virtual environment paths
        venv_bin = str(Path(NETWORK_STORAGE_VENV) / "bin")
        venv_python = str(Path(NETWORK_STORAGE_VENV) / "bin" / "python")
        
        # Update PATH to prioritize venv
        current_path = os.environ.get("PATH", "")
        if venv_bin not in current_path:
            os.environ["PATH"] = f"{venv_bin}:{current_path}"
        
        # Set Python paths
        os.environ["VIRTUAL_ENV"] = NETWORK_STORAGE_VENV
        sys.executable = venv_python
        
        # Add ComfyUI to Python path
        comfyui_path = str(NETWORK_STORAGE_COMFYUI)
        if comfyui_path not in sys.path:
            sys.path.insert(0, comfyui_path)
        
        # Update PYTHONPATH environment variable
        current_pythonpath = os.environ.get("PYTHONPATH", "")
        if comfyui_path not in current_pythonpath:
            os.environ["PYTHONPATH"] = f"{comfyui_path}:{current_pythonpath}" if current_pythonpath else comfyui_path
        
        logger.info("✅ Network storage environment activated")
        logger.info(f"🐍 Python executable: {sys.executable}")
        logger.info(f"📦 Virtual env: {os.environ.get('VIRTUAL_ENV')}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to activate network storage environment: {e}")
        return False

def clear_triton_cache():
    """Clear triton cache to fix compilation issues"""
    try:
        logger.info("🧹 Clearing triton cache...")
        
        cache_paths = [
            Path.home() / ".triton",
            Path("/tmp/.triton"),
            Path("/root/.triton"),
            Path(os.environ.get("HOME", "/root")) / ".triton"
        ]
        
        cleared_count = 0
        for cache_path in cache_paths:
            if cache_path.exists():
                try:
                    shutil.rmtree(cache_path)
                    logger.info(f"✅ Cleared triton cache: {cache_path}")
                    cleared_count += 1
                except Exception as e:
                    logger.warning(f"⚠️ Could not clear {cache_path}: {e}")
        
        if cleared_count > 0:
            logger.info(f"✅ Cleared {cleared_count} triton cache directories")
        else:
            logger.info("ℹ️ No triton cache found to clear")
        
        return True
        
    except Exception as e:
        logger.warning(f"⚠️ Error clearing triton cache: {e}")
        return False

def check_comfyui_environment():
    """Check that ComfyUI environment is properly set up"""
    try:
        logger.info("🔍 Checking ComfyUI environment...")
        
        # Check if ComfyUI can import properly
        import torch
        if torch.cuda.is_available():
            logger.info(f"🎮 CUDA available: {torch.version.cuda}")
            logger.info(f"🎮 GPU: {torch.cuda.get_device_name(0)}")
            return True
        else:
            logger.warning("⚠️ CUDA not available")
            return False
            
    except Exception as e:
        logger.error(f"❌ ComfyUI environment check failed: {e}")
        return False

def load_effects_config():
    """Load effects configuration"""
    global effects_data
    try:
        with open(EFFECTS_CONFIG, "r") as f:
            effects_data = json.load(f)
        logger.info("✅ Effects configuration loaded")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to load effects config: {str(e)}")
        return False

def start_comfyui():
    """Start ComfyUI with network storage"""
    global comfyui_process, comfyui_initialized
    
    if comfyui_initialized:
        return True
    
    try:
        logger.info("🚀 Starting ComfyUI with network storage...")
        
        # Validate network storage first
        if not validate_network_storage():
            logger.error("❌ Network storage validation failed")
            return False
        
        # Activate network storage environment
        if not activate_network_storage_environment():
            logger.error("❌ Failed to activate network storage environment")
            return False
        
        # Check ComfyUI environment
        if not check_comfyui_environment():
            logger.warning("⚠️ ComfyUI environment check failed, continuing anyway...")
        
        # Clear triton cache
        clear_triton_cache()
        time.sleep(2)
        
        # Change to ComfyUI directory
        os.chdir(COMFYUI_PATH)
        
        # Set environment for optimal performance
        env = os.environ.copy()
        env.update({
            'CUDA_VISIBLE_DEVICES': '0',
            'PYTHONPATH': f"{COMFYUI_PATH}:{env.get('PYTHONPATH', '')}",
            'PYTHONUNBUFFERED': 'true',
            'TRITON_CACHE_DIR': '/tmp/triton_runtime',
            'HF_HOME': '/workspace',
            'VIRTUAL_ENV': NETWORK_STORAGE_VENV,
            'PATH': f"{Path(NETWORK_STORAGE_VENV) / 'bin'}:{env.get('PATH', '')}"
        })
        
        # Use the network storage Python executable
        python_executable = str(Path(NETWORK_STORAGE_VENV) / "bin" / "python")
        
        # Start ComfyUI (SageAttention will be handled by workflow nodes)
        cmd = [
            python_executable, "-u", "main.py",
            "--port", "8188", 
            "--base-directory", COMFYUI_PATH,
            "--disable-auto-launch",
            "--disable-metadata",
            "--verbose", "INFO",
            "--log-stdout"
        ]
        
        logger.info("🚀 Starting ComfyUI (SageAttention handled by workflow nodes)")
        logger.info(f"🔍 ComfyUI command: {' '.join(cmd)}")
        logger.info(f"📁 Working directory: {os.getcwd()}")
        logger.info(f"🐍 Python executable: {python_executable}")
        
        # Start ComfyUI in background
        comfyui_process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Wait for ComfyUI to start and log output
        logger.info("⏳ Waiting for ComfyUI to start...")
        for attempt in range(120):  # 2 minute timeout for model loading
            try:
                response = requests.get(f"http://{COMFYUI_SERVER}/", timeout=2)
                if response.status_code == 200:
                    logger.info("✅ ComfyUI started successfully with network storage!")
                    comfyui_initialized = True
                    return True
            except requests.RequestException:
                pass
            
            # Check if process crashed and log output
            if comfyui_process.poll() is not None:
                stdout, stderr = comfyui_process.communicate()
                logger.error(f"❌ ComfyUI process crashed:")
                logger.error(f"Exit code: {comfyui_process.returncode}")
                logger.error(f"Output: {stdout}")
                return False
            
            # Log some ComfyUI output for debugging
            if attempt % 10 == 0:  # Every 10 seconds
                try:
                    line = comfyui_process.stdout.readline()
                    if line:
                        logger.info(f"ComfyUI: {line.strip()}")
                        if "sage" in line.lower() or "gpu" in line.lower():
                            logger.info(f"🎮 GPU/SageAttention INFO: {line.strip()}")
                except:
                    pass
            
            time.sleep(1)
        
        logger.error("❌ ComfyUI failed to start within timeout")
        return False
        
    except Exception as e:
        logger.error(f"❌ Error starting ComfyUI: {str(e)}")
        return False

def load_workflow():
    """Load universal workflow template"""
    try:
        with open(WORKFLOW_PATH, "r") as f:
            workflow = json.load(f)
        logger.info("✅ Universal workflow loaded")
        return workflow
    except Exception as e:
        logger.error(f"❌ Failed to load workflow: {str(e)}")
        return None

def process_input_image(image_data: str) -> Optional[str]:
    """Process and save input image"""
    try:
        if image_data.startswith("data:image"):
            image_data = image_data.split(",")[1]
        
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if needed
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # Save to ComfyUI input directory (network storage)
        filename = f"input_{uuid.uuid4().hex[:8]}.jpg"
        input_path = Path(COMFYUI_PATH) / "input" / filename
        input_path.parent.mkdir(exist_ok=True)
        
        image.save(input_path, "JPEG", quality=95)
        logger.info(f"✅ Input image saved: {filename}")
        
        return filename
        
    except Exception as e:
        logger.error(f"❌ Error processing input image: {str(e)}")
        return None

def customize_workflow(workflow: Dict, params: Dict) -> Dict:
    """Customize workflow with effect and parameters"""
    try:
        # Get effect configuration
        effects = effects_data.get('effects', {}) if effects_data else {}
        effect_config = effects.get(params['effect'], {})
        
        # Update workflow nodes by replacing placeholders
        for node_id, node in workflow.items():
            node_type = node.get("class_type", "")
            
            # Update image input node (LoadImage)
            if node_type == "LoadImage":
                if "inputs" in node and "image" in node["inputs"]:
                    if node["inputs"]["image"] == "PLACEHOLDER_IMAGE":
                        node["inputs"]["image"] = params["image_filename"]
            
            # Update LoRA selection (WanVideoLoraSelect)
            elif node_type == "WanVideoLoraSelect":
                if "inputs" in node:
                    lora_name = effect_config.get("lora", f"{params['effect']}.safetensors")
                    if node["inputs"].get("lora_name") == "PLACEHOLDER_LORA":
                        node["inputs"]["lora_name"] = lora_name
                    if node["inputs"].get("lora") == "PLACEHOLDER_LORA":
                        node["inputs"]["lora"] = lora_name
                    # Set strength from effect config
                    node["inputs"]["strength"] = effect_config.get("lora_strength", 1.0)
            
            # Update text prompts (WanVideoTextEncode)
            elif node_type == "WanVideoTextEncode":
                if "inputs" in node:
                    # Use custom prompt or effect default
                    positive_prompt = params.get("prompt", effect_config.get("prompt", ""))
                    negative_prompt = params.get("negative_prompt", effect_config.get("negative_prompt", ""))
                    
                    if node["inputs"].get("positive_prompt") == "PLACEHOLDER_PROMPT":
                        node["inputs"]["positive_prompt"] = positive_prompt
                    if node["inputs"].get("negative_prompt") == "PLACEHOLDER_NEGATIVE_PROMPT":
                        node["inputs"]["negative_prompt"] = negative_prompt
            
            # Update sampling parameters (WanVideoSampler)
            elif node_type == "WanVideoSampler":
                if "inputs" in node:
                    node["inputs"]["steps"] = params.get("steps", 10)
                    node["inputs"]["cfg"] = params.get("cfg", 6)
                    node["inputs"]["seed"] = params.get("seed", -1)
                    node["inputs"]["frames"] = params.get("frames", 85)
            
            # Update video output parameters
            elif node_type == "VHS_VideoCombine":
                if "inputs" in node:
                    node["inputs"]["frame_rate"] = params.get("fps", 16)
            
            # Update image encoding parameters
            elif node_type == "WanVideoImageClipEncode":
                if "inputs" in node:
                    node["inputs"]["generation_width"] = params.get("width", 720)
                    node["inputs"]["generation_height"] = params.get("height", 720)
                    node["inputs"]["num_frames"] = params.get("frames", 85)
            
            # SageAttention is already set in the workflow
            elif node_type == "WanVideoModelLoader":
                if "inputs" in node:
                    logger.info("🎯 Found WanVideoModelLoader with SageAttention mode")
        
        logger.info(f"✅ Workflow customized for effect: {params['effect']}")
        return workflow
        
    except Exception as e:
        logger.error(f"❌ Error customizing workflow: {str(e)}")
        return workflow

def submit_workflow(workflow: Dict) -> Optional[str]:
    """Submit workflow to ComfyUI"""
    try:
        response = requests.post(
            f"http://{COMFYUI_SERVER}/prompt",
            json={"prompt": workflow},
            timeout=30
        )
        
        # Log the response before raising for status
        if response.status_code != 200:
            logger.error(f"❌ ComfyUI rejected workflow:")
            logger.error(f"Status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            
        response.raise_for_status()
        
        result = response.json()
        prompt_id = result.get("prompt_id")
        
        if prompt_id:
            logger.info(f"✅ Workflow submitted: {prompt_id}")
            return prompt_id
        else:
            logger.error("❌ No prompt_id in response")
            return None
        
    except Exception as e:
        logger.error(f"❌ Error submitting workflow: {str(e)}")
        return None

def wait_for_completion(prompt_id: str) -> Optional[str]:
    """Wait for workflow completion and return output path"""
    try:
        start_time = time.time()
        
        while True:
            try:
                # Check status
                response = requests.get(f"http://{COMFYUI_SERVER}/history/{prompt_id}")
                if response.status_code == 200:
                    history = response.json()
                    
                    if prompt_id in history:
                        outputs = history[prompt_id].get("outputs", {})
                        
                        # Look for video output
                        for node_outputs in outputs.values():
                            if "videos" in node_outputs:
                                video_info = node_outputs["videos"][0]
                                video_path = Path(COMFYUI_PATH) / "output" / video_info["filename"]
                                
                                if video_path.exists():
                                    logger.info(f"✅ Video generated: {video_path}")
                                    return str(video_path)
                
                # Log progress every minute
                elapsed = time.time() - start_time
                if elapsed % 60 < 2:
                    logger.info(f"⏳ Still processing... ({elapsed/60:.1f} minutes elapsed)")
                
            except Exception as e:
                logger.warning(f"⚠️ Error checking status: {e}")
            
            time.sleep(2)
        
    except Exception as e:
        logger.error(f"❌ Error waiting for completion: {str(e)}")
        return None

def encode_video_to_base64(video_path: str) -> Optional[str]:
    """Encode video file to base64"""
    try:
        with open(video_path, "rb") as f:
            video_data = f.read()
        
        video_base64 = base64.b64encode(video_data).decode('utf-8')
        logger.info(f"✅ Video encoded ({len(video_data)} bytes)")
        
        return video_base64
        
    except Exception as e:
        logger.error(f"❌ Error encoding video: {str(e)}")
        return None

def check_gpu_memory():
    """Check GPU memory usage with better diagnostics"""
    try:
        import torch
        
        # Check if CUDA is available
        if not torch.cuda.is_available():
            logger.warning("⚠️ CUDA not available - models will run on CPU")
            return
        
        # Check GPU info
        gpu_count = torch.cuda.device_count()
        current_device = torch.cuda.current_device()
        gpu_name = torch.cuda.get_device_name(current_device)
        
        logger.info(f"🎮 GPU Info: {gpu_name} (Device {current_device}/{gpu_count})")
        
        # Get memory info
        memory_allocated = torch.cuda.memory_allocated(current_device) / 1024**3  # GB
        memory_cached = torch.cuda.memory_reserved(current_device) / 1024**3      # GB
        
        # Get total GPU memory
        total_memory = torch.cuda.get_device_properties(current_device).total_memory / 1024**3  # GB
        
        logger.info(f"🔍 GPU Memory - Allocated: {memory_allocated:.1f}GB, Cached: {memory_cached:.1f}GB, Total: {total_memory:.1f}GB")
        
        # If no memory allocated, try to trigger CUDA initialization
        if memory_allocated == 0.0 and memory_cached == 0.0:
            logger.info("🔧 Initializing CUDA context...")
            dummy_tensor = torch.zeros(1).cuda()
            del dummy_tensor
            torch.cuda.empty_cache()
            
            # Check again after initialization
            memory_allocated = torch.cuda.memory_allocated(current_device) / 1024**3
            memory_cached = torch.cuda.memory_reserved(current_device) / 1024**3
            logger.info(f"🔍 GPU Memory (after init) - Allocated: {memory_allocated:.1f}GB, Cached: {memory_cached:.1f}GB")
        
    except Exception as e:
        logger.warning(f"⚠️ Could not check GPU memory: {e}")

def handler(job):
    """Main RunPod handler"""
    try:
        logger.info("🎬 Processing job with network storage SageAttention...")
        
        # Validate network storage setup first
        if not validate_network_storage():
            return {"error": "Network storage validation failed - ensure your RunPod endpoint is using the correct network storage"}
        
        # Activate network storage environment
        if not activate_network_storage_environment():
            return {"error": "Failed to activate network storage environment"}
        
        # Check GPU memory at start
        check_gpu_memory()
        
        # Load effects config if not loaded
        if not effects_data and not load_effects_config():
            logger.warning("⚠️ Effects config not loaded - using defaults")
        
        # Start ComfyUI (SageAttention will be handled by workflow nodes)
        if not start_comfyui():
            return {"error": "Failed to start ComfyUI from network storage"}
        
        # Load workflow template
        workflow = load_workflow()
        if not workflow:
            return {"error": "Failed to load workflow"}
        
        # Get job input
        job_input = job.get("input", {})
        
        # Process input image
        image_data = job_input.get("image")
        if not image_data:
            return {"error": "No image provided"}
        
        image_filename = process_input_image(image_data)
        if not image_filename:
            return {"error": "Failed to process input image"}
        
        # Prepare parameters
        params = {
            "image_filename": image_filename,
            "effect": job_input.get("effect", "ghostrider"),
            "prompt": job_input.get("prompt"),
            "negative_prompt": job_input.get("negative_prompt"),
            "steps": job_input.get("steps", 10),
            "cfg": job_input.get("cfg", 6),
            "frames": job_input.get("frames", 85),
            "fps": job_input.get("fps", 16),
            "width": job_input.get("width", 720),
            "height": job_input.get("height", 720),
            "seed": job_input.get("seed", -1)
        }
        
        logger.info(f"🎭 Processing effect: {params['effect']} with ComfyUI SageAttention nodes")
        
        # Customize workflow
        workflow = customize_workflow(workflow, params)
        
        # Submit workflow
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {"error": "Failed to submit workflow"}
        
        # Wait for completion (no timeout - let RunPod handle it)
        video_path = wait_for_completion(prompt_id)
        if not video_path:
            return {"error": "Video generation failed or timed out"}
        
        # Encode result
        video_base64 = encode_video_to_base64(video_path)
        if not video_base64:
            return {"error": "Failed to encode output video"}
        
        # Check GPU memory at end
        check_gpu_memory()
        
        # Clean up
        try:
            input_path = Path(COMFYUI_PATH) / "input" / image_filename
            if input_path.exists():
                input_path.unlink()
                logger.info("✅ Cleaned up input image")
        except:
            pass
        
        return {
            "video": video_base64,
            "effect": params["effect"],
            "prompt_id": prompt_id,
            "filename": Path(video_path).name,
            "processing_time": time.time(),
            "sage_attention_used": True,  # Used by ComfyUI workflow nodes
            "network_storage_used": True
        }
        
    except Exception as e:
        logger.error(f"❌ Handler error: {str(e)}")
        return {"error": f"Processing failed: {str(e)}"}

# Initialize on startup
if __name__ == "__main__":
    logger.info("🚀 Starting AI-Avatarka Worker with Network Storage...")
    logger.info("📁 Using network storage for all dependencies and models")
    logger.info("🧠 SageAttention setup from network storage")
    
    logger.info("🎯 Starting RunPod serverless worker...")
    runpod.serverless.start({"handler": handler})