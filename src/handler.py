"""
AI-Avatarka RunPod Serverless Worker Handler
Fixed triton tokenization error with proper SageAttention startup
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

# Constants
COMFYUI_PATH = "/workspace/ComfyUI"
COMFYUI_SERVER = "127.0.0.1:8188"
EFFECTS_CONFIG = "/workspace/prompts/effects.json"
WORKFLOW_PATH = "/workspace/ComfyUI/workflow/universal_i2v.json"

# Global state
comfyui_process = None
comfyui_initialized = False
effects_data = None

def clear_triton_cache():
    """Clear triton cache to fix Python 3.12 tokenization errors"""
    try:
        logger.info("🧹 Clearing triton cache (Python 3.12 fix)...")
        
        # Find triton cache directories
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

def build_sageattention_with_cache_fix():
    """Build SageAttention - AVOID RUNTIME DEPENDENCY CONFLICTS FROM LOGS"""
    try:
        # CRITICAL: Check if already available first
        try:
            from sageattention import sageattn
            logger.info("✅ SageAttention already available, skipping build")
            return True
        except ImportError:
            pass
        
        logger.info("🔧 Building SageAttention with FIXED dependency management...")
        
        # CRITICAL: DON'T reinstall triton/torch/xformers at runtime like the logs show
        # This caused massive dependency conflicts in your logs:
        # - torch 2.4.1 -> 2.7.1 (incompatible with torchaudio/torchvision)
        # - numpy 2.3.1 (incompatible with scipy, cupy, mediapipe, numba)
        # - triton 3.0.0 -> 3.3.1 (caused tokenization errors)
        
        logger.info("⚠️ AVOIDING dependency reinstallation that caused failures in logs")
        logger.info("📋 Using existing torch/triton versions to prevent conflicts")
        
        # Clear triton cache without reinstalling anything
        clear_triton_cache()
        
        # Set minimal environment for compilation
        env = os.environ.copy()
        env.update({
            'TORCH_CUDA_ARCH_LIST': '8.6;8.9;9.0',
            'CUDA_VISIBLE_DEVICES': '0',
            'MAX_JOBS': '2',  # Reduced to prevent memory issues
            'PYTHONDONTWRITEBYTECODE': '1',
            'TRITON_CACHE_DIR': '/tmp/triton_build_cache'
        })
        
        # Create temp build directory
        build_dir = Path("/tmp/sageattention_build_fixed")
        if build_dir.exists():
            subprocess.run(["rm", "-rf", str(build_dir)], check=True)
        
        logger.info("📥 Cloning SageAttention...")
        subprocess.run([
            "git", "clone", "--depth", "1",
            "https://github.com/thu-ml/SageAttention.git",
            str(build_dir)
        ], check=True, env=env, timeout=120)
        
        # Build WITHOUT touching existing dependencies
        logger.info("🔨 Building SageAttention (preserving existing dependencies)...")
        
        result = subprocess.run([
            sys.executable, "setup.py", "build_ext", "--inplace"
        ], cwd=str(build_dir), env=env, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            logger.warning(f"⚠️ setup.py build failed, trying pip install...")
            # Try pip install as last resort but without --force-reinstall
            result = subprocess.run([
                sys.executable, "-m", "pip", "install",
                "--no-cache-dir",
                "--no-deps",  # CRITICAL: Don't install dependencies
                "."
            ], cwd=str(build_dir), env=env, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            logger.error(f"❌ SageAttention build failed:")
            logger.error(f"STDOUT: {result.stdout}")
            logger.error(f"STDERR: {result.stderr}")
            logger.warning("⚠️ Will continue without SageAttention")
            return False
        else:
            logger.info("✅ SageAttention build succeeded")
        
        # Cleanup
        subprocess.run(["rm", "-rf", str(build_dir)], check=False)
        clear_triton_cache()
        
        # Verification
        try:
            from sageattention import sageattn
            logger.info("✅ SageAttention verified and ready!")
            return True
        except ImportError as e:
            logger.warning(f"⚠️ SageAttention import failed: {e}")
            logger.info("Will continue without SageAttention")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("❌ SageAttention build timed out")
        return False
    except Exception as e:
        logger.error(f"❌ SageAttention build error: {e}")
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
    """Start ComfyUI server - FIXED based on logs analysis"""
    global comfyui_process, comfyui_initialized
    
    if comfyui_initialized:
        return True
    
    try:
        logger.info("🚀 Starting ComfyUI server (FIXED from logs analysis)...")
        
        # Build SageAttention WITHOUT dependency conflicts
        logger.info("🔧 Building SageAttention (avoiding dependency conflicts from logs)...")
        sage_available = build_sageattention_with_cache_fix()
        
        # Clear cache one more time
        clear_triton_cache()
        time.sleep(2)
        
        # Start ComfyUI with proper environment
        os.chdir(COMFYUI_PATH)
        
        env = os.environ.copy()
        env.update({
            'CUDA_VISIBLE_DEVICES': '0',
            'PYTHONPATH': f"{COMFYUI_PATH}:{env.get('PYTHONPATH', '')}",
            'PYTHONDONTWRITEBYTECODE': '1',
            'TRITON_CACHE_DIR': '/tmp/triton_runtime'
        })
        
        # CRITICAL: Start ComfyUI command based on working script
        cmd = [
            sys.executable, "main.py",
            "--listen", "127.0.0.1",
            "--port", "8188",
            "--disable-auto-launch",
            "--disable-metadata"
        ]
        
        # CRITICAL: Only add SageAttention flag if build succeeded 
        # Your logs show ComfyUI crashed with torchvision::nms error after SageAttention
        if sage_available:
            cmd.append("--use-sage-attention")
            logger.info("🚀 Starting ComfyUI WITH SageAttention enabled")
        else:
            logger.info("🚀 Starting ComfyUI WITHOUT SageAttention (build issues)")
        
        logger.info(f"🔍 ComfyUI startup command: {' '.join(cmd)}")
        
        comfyui_process = subprocess.Popen(
            cmd,
            cwd=COMFYUI_PATH, 
            env=env, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )
        
        # Wait for server with improved error handling
        for i in range(180):  # 3 minute timeout
            try:
                response = requests.get(f"http://{COMFYUI_SERVER}/", timeout=5)
                if response.status_code == 200:
                    comfyui_initialized = True
                    logger.info("✅ ComfyUI server started successfully")
                    
                    # Check final SageAttention status
                    if sage_available:
                        try:
                            from sageattention import sageattn
                            logger.info("✅ SageAttention working with ComfyUI")
                        except Exception as e:
                            logger.warning(f"⚠️ SageAttention not available: {e}")
                    
                    return True
                    
            except requests.exceptions.RequestException:
                if comfyui_process.poll() is not None:
                    stdout, stderr = comfyui_process.communicate()
                    logger.error("❌ ComfyUI crashed during startup:")
                    logger.error(f"STDOUT: {stdout.decode()}")
                    logger.error(f"STDERR: {stderr.decode()}")
                    
                    # From logs: Check for specific errors
                    stderr_str = stderr.decode()
                    if "operator torchvision::nms does not exist" in stderr_str:
                        logger.error("🔍 torchvision::nms error detected - dependency conflict!")
                        logger.error("💡 This is caused by version mismatches in torch/torchvision")
                    
                    return False
                time.sleep(1)
        
        logger.error("❌ ComfyUI startup timeout")
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
        
        # Generate unique filename
        filename = f"input_{uuid.uuid4().hex[:8]}.png"
        filepath = Path(COMFYUI_PATH) / "input" / filename
        
        # Ensure input directory exists
        filepath.parent.mkdir(exist_ok=True)
        
        # Save image
        image.save(filepath, format='PNG')
        logger.info(f"✅ Input image saved: {filename}")
        
        return filename
        
    except Exception as e:
        logger.error(f"❌ Error processing input image: {str(e)}")
        return None

def customize_workflow(workflow: Dict, params: Dict) -> Dict:
    """Customize workflow with user parameters"""
    try:
        # Load effect configuration
        effect_name = params.get("effect", "ghostrider")
        if not effects_data or effect_name not in effects_data:
            logger.warning(f"Effect '{effect_name}' not found, using default")
            effect_name = "ghostrider"
        
        effect_config = effects_data.get(effect_name, {})
        
        # Update workflow nodes with parameters
        for node_id, node in workflow.items():
            node_type = node.get("class_type", "")
            
            # Update image input
            if node_type == "LoadImage":
                node["inputs"]["image"] = params["image_filename"]
            
            # Update LoRA
            elif node_type == "LoraLoader":
                lora_file = f"{effect_name}.safetensors"
                node["inputs"]["lora_name"] = lora_file
                logger.info(f"🎭 Using LoRA: {lora_file}")
            
            # Update positive prompt
            elif node_type == "CLIPTextEncode" and "positive" in str(node):
                base_prompt = effect_config.get("positive_prompt", "")
                user_prompt = params.get("prompt", "")
                combined_prompt = f"{base_prompt}, {user_prompt}" if user_prompt else base_prompt
                node["inputs"]["text"] = combined_prompt
                logger.info(f"🎯 Positive prompt: {combined_prompt[:100]}...")
            
            # Update negative prompt
            elif node_type == "CLIPTextEncode" and "negative" in str(node):
                base_negative = effect_config.get("negative_prompt", "")
                user_negative = params.get("negative_prompt", "")
                combined_negative = f"{base_negative}, {user_negative}" if user_negative else base_negative
                node["inputs"]["text"] = combined_negative
            
            # Update sampling parameters
            elif node_type == "KSampler":
                node["inputs"]["steps"] = params.get("steps", 10)
                node["inputs"]["cfg"] = params.get("cfg", 6)
                node["inputs"]["seed"] = params.get("seed", -1)
            
            # Update video parameters
            elif "video" in node_type.lower():
                if "fps" in node["inputs"]:
                    node["inputs"]["fps"] = params.get("fps", 16)
                if "frame_count" in node["inputs"]:
                    node["inputs"]["frame_count"] = params.get("frames", 85)
        
        logger.info("✅ Workflow customized successfully")
        return workflow
        
    except Exception as e:
        logger.error(f"❌ Error customizing workflow: {str(e)}")
        return workflow

def submit_workflow(workflow: Dict) -> Optional[str]:
    """Submit workflow to ComfyUI"""
    try:
        prompt_id = str(uuid.uuid4())
        
        payload = {
            "prompt": workflow,
            "client_id": prompt_id
        }
        
        response = requests.post(
            f"http://{COMFYUI_SERVER}/prompt",
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Workflow submitted: {prompt_id}")
            return prompt_id
        else:
            logger.error(f"❌ Failed to submit workflow: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error submitting workflow: {str(e)}")
        return None

def wait_for_completion(prompt_id: str, timeout: int = 300) -> Optional[str]:
    """Wait for workflow completion and return output path"""
    try:
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check if process completed
            try:
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
                
            except Exception as e:
                logger.warning(f"⚠️ Error checking status: {e}")
            
            time.sleep(2)
        
        logger.error("❌ Video generation timeout")
        return None
        
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

def handler(job):
    """Main RunPod handler"""
    try:
        logger.info("🎬 Processing job...")
        
        # Get job input
        job_input = job.get("input", {})
        
        # Start ComfyUI if not already running
        if not start_comfyui():
            return {"error": "Failed to start ComfyUI"}
        
        # Load workflow template
        workflow = load_workflow()
        if not workflow:
            return {"error": "Failed to load workflow"}
        
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
        
        logger.info(f"🎭 Processing effect: {params['effect']}")
        
        workflow = customize_workflow(workflow, params)
        
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {"error": "Failed to submit workflow"}
        
        video_path = wait_for_completion(prompt_id)
        if not video_path:
            return {"error": "Video generation failed or timed out"}
        
        video_base64 = encode_video_to_base64(video_path)
        if not video_base64:
            return {"error": "Failed to encode output video"}
        
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
            "processing_time": time.time()
        }
        
    except Exception as e:
        logger.error(f"❌ Handler error: {str(e)}")
        return {"error": f"Processing failed: {str(e)}"}

# Initialize on startup
if __name__ == "__main__":
    logger.info("🚀 Initializing AI-Avatarka Worker (Python 3.12 Compatible)...")
    logger.info("ℹ️ SageAttention will be built and ComfyUI started with --use-sage-attention flag")
    
    load_effects_config()
    
    logger.info("🎯 Starting RunPod serverless worker...")
    logger.info("⏳ Ready for jobs...")
    runpod.serverless.start({"handler": handler})