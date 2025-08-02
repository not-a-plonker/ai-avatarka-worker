"""
AI-Avatarka RunPod Serverless Worker Handler
FIXED VERSION - No infinite loop, proper status, correct paths
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
NETWORK_STORAGE_COMFYUI = os.environ.get("COMFYUI_PATH", "/workspace/ComfyUI")

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
    """ComfyUI already started by start.sh - just check if it's ready"""
    global comfyui_initialized
    
    if comfyui_initialized:
        return True
    
    try:
        logger.info("🔍 Checking if ComfyUI is ready...")
        
        # Reduced timeout and better error handling
        for attempt in range(90):  # 90 seconds timeout
            try:
                response = requests.get(f"http://{COMFYUI_SERVER}/", timeout=5)
                if response.status_code == 200:
                    logger.info("✅ ComfyUI is ready!")
                    comfyui_initialized = True
                    return True
            except requests.RequestException as e:
                if attempt % 5 == 0:  # Log every 5 seconds
                    logger.info(f"⏳ Waiting for ComfyUI... ({attempt}/90)")
            
            time.sleep(1)
        
        logger.error("❌ ComfyUI not ready within 90 seconds")
        return False
        
    except Exception as e:
        logger.error(f"❌ Error checking ComfyUI: {str(e)}")
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
    """Customize workflow with effect and parameters - WITH DEBUGGING"""
    try:
        # Get effect configuration
        effects = effects_data.get('effects', {}) if effects_data else {}
        effect_config = effects.get(params['effect'], {})
        
        # DEBUG: Log what prompts we're trying to use
        positive_prompt = params.get("prompt", effect_config.get("prompt", ""))
        negative_prompt = params.get("negative_prompt", effect_config.get("negative_prompt", ""))
        
        logger.info(f"🎭 EFFECT CONFIG FOR {params['effect']}:")
        logger.info(f"📝 POSITIVE PROMPT: {positive_prompt}")
        logger.info(f"❌ NEGATIVE PROMPT: {negative_prompt}")
        logger.info(f"🎯 LORA: {effect_config.get('lora', 'NONE')}")
        
        # Update workflow nodes by replacing placeholders
        prompt_nodes_found = 0
        placeholder_found = False
        
        for node_id, node in workflow.items():
            node_type = node.get("class_type", "")
            
            # Update image input node (LoadImage)
            if node_type == "LoadImage":
                if "inputs" in node and "image" in node["inputs"]:
                    logger.info(f"🖼️ LoadImage node {node_id}: current image = {node['inputs']['image']}")
                    if node["inputs"]["image"] == "PLACEHOLDER_IMAGE":
                        node["inputs"]["image"] = params["image_filename"]
                        logger.info(f"✅ Set image to: {params['image_filename']}")
                        placeholder_found = True
            
            # Update LoRA selection (WanVideoLoraSelect)
            elif node_type == "WanVideoLoraSelect":
                if "inputs" in node:
                    lora_name = effect_config.get("lora", f"{params['effect']}.safetensors")
                    logger.info(f"🎯 LoRA node {node_id}: current lora = {node['inputs'].get('lora_name', 'NONE')}")
                    
                    if node["inputs"].get("lora_name") == "PLACEHOLDER_LORA":
                        node["inputs"]["lora_name"] = lora_name
                        logger.info(f"✅ Set lora_name to: {lora_name}")
                        placeholder_found = True
                    if node["inputs"].get("lora") == "PLACEHOLDER_LORA":
                        node["inputs"]["lora"] = lora_name
                        logger.info(f"✅ Set lora to: {lora_name}")
                        placeholder_found = True
                    
                    # Set strength from effect config
                    node["inputs"]["strength"] = effect_config.get("lora_strength", 1.0)
                    logger.info(f"✅ Set lora strength to: {effect_config.get('lora_strength', 1.0)}")
            
            # Update text prompts (WanVideoTextEncode) - THIS IS THE IMPORTANT ONE
            elif node_type == "WanVideoTextEncode":
                prompt_nodes_found += 1
                if "inputs" in node:
                    logger.info(f"📝 TEXT NODE {node_id} FOUND:")
                    logger.info(f"   Current positive_prompt: {node['inputs'].get('positive_prompt', 'NONE')}")
                    logger.info(f"   Current negative_prompt: {node['inputs'].get('negative_prompt', 'NONE')}")
                    
                    # Check for placeholders and replace
                    if node["inputs"].get("positive_prompt") == "PLACEHOLDER_PROMPT":
                        node["inputs"]["positive_prompt"] = positive_prompt
                        logger.info(f"✅ REPLACED positive_prompt with: {positive_prompt[:100]}...")
                        placeholder_found = True
                    elif "positive_prompt" in node["inputs"]:
                        logger.warning(f"⚠️ positive_prompt exists but is NOT placeholder: '{node['inputs']['positive_prompt']}'")
                    
                    if node["inputs"].get("negative_prompt") == "PLACEHOLDER_NEGATIVE_PROMPT":
                        node["inputs"]["negative_prompt"] = negative_prompt
                        logger.info(f"✅ REPLACED negative_prompt with: {negative_prompt}")
                        placeholder_found = True
                    elif "negative_prompt" in node["inputs"]:
                        logger.warning(f"⚠️ negative_prompt exists but is NOT placeholder: '{node['inputs']['negative_prompt']}'")
                    
                    # Log final values
                    logger.info(f"📋 FINAL VALUES for node {node_id}:")
                    logger.info(f"   positive_prompt: {node['inputs'].get('positive_prompt', 'NONE')[:100]}...")
                    logger.info(f"   negative_prompt: {node['inputs'].get('negative_prompt', 'NONE')}")
            
            # Update sampling parameters (WanVideoSampler)
            elif node_type == "WanVideoSampler":
                if "inputs" in node:
                    node["inputs"]["steps"] = params.get("steps", 20)
                    node["inputs"]["cfg"] = params.get("cfg", 6)
                    node["inputs"]["seed"] = params.get("seed", 812989658032619)
                    node["inputs"]["frames"] = params.get("frames", 85)
                    logger.info(f"⚙️ Sampler node {node_id}: steps={params.get('steps', 20)}, cfg={params.get('cfg', 6)}")
            
            # Update video output parameters
            elif node_type == "VHS_VideoCombine":
                if "inputs" in node:
                    node["inputs"]["frame_rate"] = params.get("fps", 16)
            
            # Update image encoding parameters
            elif node_type == "WanVideoImageClipEncode":
                if "inputs" in node:
                    node["inputs"]["generation_width"] = params.get("width", 480)
                    node["inputs"]["generation_height"] = params.get("height", 480)
                    node["inputs"]["num_frames"] = params.get("frames", 85)
            
            # SageAttention is already set in the workflow
            elif node_type == "WanVideoModelLoader":
                if "inputs" in node:
                    logger.info("🎯 Found WanVideoModelLoader with SageAttention mode")
        
        # Summary logging
        logger.info(f"📊 WORKFLOW CUSTOMIZATION SUMMARY:")
        logger.info(f"   Text nodes found: {prompt_nodes_found}")
        logger.info(f"   Placeholders found and replaced: {placeholder_found}")
        
        if prompt_nodes_found == 0:
            logger.error("❌ NO WanVideoTextEncode nodes found in workflow!")
        
        if not placeholder_found:
            logger.warning("⚠️ NO placeholders found - workflow might have hardcoded values!")
        
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
    """FIXED: Wait for workflow completion - handle actual ComfyUI output format"""
    try:
        start_time = time.time()
        
        while True:
            try:
                # Check ComfyUI history for THIS specific prompt_id
                response = requests.get(f"http://{COMFYUI_SERVER}/history/{prompt_id}")
                response.close()
                if response.status_code == 200:
                    history = response.json()
                    
                    if prompt_id in history:
                        prompt_info = history[prompt_id]
                        status = prompt_info.get("status", {})
                        
                        # Check if completed
                        if status.get("completed", False):
                            logger.info(f"✅ Workflow completed for {prompt_id}")
                            outputs = prompt_info.get("outputs", {})
                            
                            # Look for video output in any node - try multiple formats
                            for node_id, node_outputs in outputs.items():
                                logger.info(f"🔍 Checking node {node_id} with keys: {list(node_outputs.keys())}")
                                
                                # Method 1: Look for "videos" key (standard format)
                                if "videos" in node_outputs and len(node_outputs["videos"]) > 0:
                                    video_info = node_outputs["videos"][0]
                                    filename = video_info.get("filename")
                                    if filename:
                                        video_path = Path("/workspace/ComfyUI/output") / filename
                                        if video_path.exists():
                                            logger.info(f"✅ Found video via 'videos' key: {video_path}")
                                            return str(video_path)
                                
                                # Method 2: Look for "fullpath" in any output structure
                                def find_fullpath(obj):
                                    if isinstance(obj, dict):
                                        if "fullpath" in obj:
                                            return obj["fullpath"]
                                        for value in obj.values():
                                            result = find_fullpath(value)
                                            if result:
                                                return result
                                    elif isinstance(obj, list):
                                        for item in obj:
                                            result = find_fullpath(item)
                                            if result:
                                                return result
                                    return None
                                
                                fullpath = find_fullpath(node_outputs)
                                if fullpath:
                                    video_path = Path(fullpath)
                                    if video_path.exists():
                                        logger.info(f"✅ Found video via 'fullpath': {video_path}")
                                        return str(video_path)
                                
                                # Method 3: Look for any .mp4 files mentioned in the output
                                output_str = str(node_outputs)
                                if ".mp4" in output_str:
                                    import re
                                    mp4_matches = re.findall(r'["\']([^"\']*\.mp4)["\']', output_str)
                                    for match in mp4_matches:
                                        if match.startswith('/'):
                                            video_path = Path(match)
                                        else:
                                            video_path = Path("/workspace/ComfyUI/output") / match
                                        
                                        if video_path.exists():
                                            logger.info(f"✅ Found video via regex: {video_path}")
                                            return str(video_path)
                            
                            # Method 4: Last resort - look for newest .mp4 file in output directory
                            output_dir = Path("/workspace/ComfyUI/output")
                            if output_dir.exists():
                                mp4_files = list(output_dir.glob("*.mp4"))
                                if mp4_files:
                                    # Get the newest mp4 file created after workflow started
                                    newest_video = max(mp4_files, key=lambda f: f.stat().st_mtime)
                                    if newest_video.stat().st_mtime > start_time:
                                        logger.info(f"✅ Found newest video file: {newest_video}")
                                        return str(newest_video)
                            
                            # If we get here, workflow completed but no video found
                            logger.error(f"❌ Workflow completed but no video output found for {prompt_id}")
                            logger.info(f"🔍 Full outputs structure: {json.dumps(outputs, indent=2)}")
                            return None
                        
                        # Check if failed
                        elif "error" in status or status.get("status_str") == "error":
                            logger.error(f"❌ Workflow failed for {prompt_id}: {status}")
                            return None
                
                # Log progress every 30 seconds
                elapsed = time.time() - start_time
                if elapsed % 30 < 2:
                    logger.info(f"⏳ Still processing {prompt_id}... ({elapsed:.1f}s elapsed)")
                
            except Exception as e:
                logger.warning(f"⚠️ Error checking status for {prompt_id}: {e}")
            
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
    """FIXED: Main RunPod handler with proper status and no infinite loop"""
    start_time = time.time()
    
    try:
        logger.info("🎬 Processing job with network storage SageAttention...")
        
        # Validate network storage setup first
        if not validate_network_storage():
            return {
                "error": "Network storage validation failed",
                "status": "FAILED",
                "success": False
            }
        
        # Activate network storage environment
        if not activate_network_storage_environment():
            return {
                "error": "Failed to activate network storage environment",
                "status": "FAILED", 
                "success": False
            }
        
        # Check GPU memory at start
        check_gpu_memory()
        
        # Load effects config if not loaded
        if not effects_data and not load_effects_config():
            logger.warning("⚠️ Effects config not loaded - using defaults")
        
        # Start ComfyUI
        if not start_comfyui():
            return {
                "error": "Failed to start ComfyUI from network storage",
                "status": "FAILED",
                "success": False
            }
        
        # Load workflow template
        workflow = load_workflow()
        if not workflow:
            return {
                "error": "Failed to load workflow",
                "status": "FAILED",
                "success": False
            }
        
        # Get job input
        job_input = job.get("input", {})
        
        # Process input image
        image_data = job_input.get("image")
        if not image_data:
            return {
                "error": "No image provided",
                "status": "FAILED",
                "success": False
            }
        
        image_filename = process_input_image(image_data)
        if not image_filename:
            return {
                "error": "Failed to process input image",
                "status": "FAILED",
                "success": False
            }
        
        # Prepare parameters
        params = {
            "image_filename": image_filename,
            "effect": job_input.get("effect", "ghostrider"),
            "prompt": job_input.get("prompt"),
            "negative_prompt": job_input.get("negative_prompt"),
            "steps": job_input.get("steps", 20),
            "cfg": job_input.get("cfg", 6),
            "frames": job_input.get("frames", 85),
            "fps": job_input.get("fps", 16),
            "width": job_input.get("width", 480),
            "height": job_input.get("height", 480),
            "seed": job_input.get("seed", 812989658032619)
        }
        
        logger.info(f"🔍 PARAMS RECEIVED: width={params.get('width')}, height={params.get('height')}, steps={params.get('steps')}")

        logger.info(f"🎭 Processing effect: {params['effect']}")
        
        # Customize workflow
        workflow = customize_workflow(workflow, params)
        
        # Submit workflow
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {
                "error": "Failed to submit workflow",
                "status": "FAILED",
                "success": False
            }
        
        logger.info(f"✅ Workflow submitted with prompt_id: {prompt_id}")
        
        # FIXED: Wait for completion with proper loop handling
        video_path = wait_for_completion(prompt_id)
        if not video_path:
            return {
                "error": "Video generation failed or timed out",
                "status": "FAILED",
                "success": False,
                "prompt_id": prompt_id
            }
        
        # Encode result
        video_base64 = encode_video_to_base64(video_path)
        if not video_base64:
            return {
                "error": "Failed to encode output video",
                "status": "FAILED", 
                "success": False,
                "prompt_id": prompt_id
            }
        
        processing_time = time.time() - start_time
        logger.info(f"✅ Processing completed in {processing_time:.2f} seconds")
        
        # Clean up input file
        try:
            input_path = Path(COMFYUI_PATH) / "input" / image_filename
            if input_path.exists():
                input_path.unlink()
                logger.info("✅ Cleaned up input image")
        except Exception as cleanup_error:
            logger.warning(f"⚠️ Cleanup failed: {cleanup_error}")
        
        # FIXED: Return proper success response with explicit status
        result = {
            "video": video_base64,
            "effect": params["effect"],
            "prompt_id": prompt_id,
            "filename": Path(video_path).name,
            "processing_time": processing_time,
            "status": "COMPLETED",    # EXPLICIT STATUS for RunPod
            "success": True,          # SUCCESS FLAG
            "sage_attention_used": True,
            "network_storage_used": True
        }
        
        logger.info(f"🎉 Returning successful result for effect: {params['effect']}")
        logger.info(f"📝 Result keys: {list(result.keys())}")
        
        return result
        
    except Exception as e:
        processing_time = time.time() - start_time
        error_msg = f"Processing failed after {processing_time:.2f}s: {str(e)}"
        logger.error(f"❌ Handler error: {error_msg}")
        
        return {
            "error": error_msg,
            "status": "FAILED",      # EXPLICIT FAILED STATUS
            "success": False,
            "processing_time": processing_time
        }

# Initialize on startup
if __name__ == "__main__":
    logger.info("🚀 Starting AI-Avatarka Worker with Network Storage...")
    logger.info("📁 Using network storage for all dependencies and models")
    logger.info("🧠 SageAttention setup from network storage")
    
    logger.info("🎯 Starting RunPod serverless worker...")
    runpod.serverless.start({"handler": handler})
