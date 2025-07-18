"""
AI-Avatarka RunPod Serverless Worker Handler
Fixes Python 3.12 triton tokenization error by clearing cache
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
    """Build SageAttention with triton cache clearing"""
    try:
        # First check if already available
        try:
            from sageattention import sageattn
            logger.info("✅ SageAttention already available, skipping build")
            return True
        except ImportError:
            pass
        
        logger.info("🔧 Building SageAttention with Python 3.12 fixes...")
        
        # CRITICAL: Clear triton cache first
        clear_triton_cache()
        
        # Set environment variables for compilation
        env = os.environ.copy()
        env.update({
            'TORCH_CUDA_ARCH_LIST': '8.6;8.9;9.0',
            'CUDA_VISIBLE_DEVICES': '0',
            'MAX_JOBS': '4',
            'NINJA_STATUS': '[%f/%t] ',
            # Python 3.12 specific fixes
            'PYTHONDONTWRITEBYTECODE': '1',  # Prevent .pyc cache issues
            'TRITON_CACHE_DIR': '/tmp/triton_build_cache'  # Use temp cache
        })
        
        # Create temp build directory
        build_dir = Path("/tmp/sageattention_python312_build")
        if build_dir.exists():
            subprocess.run(["rm", "-rf", str(build_dir)], check=True)
        
        # Also create clean triton cache dir
        triton_cache = Path("/tmp/triton_build_cache")
        if triton_cache.exists():
            subprocess.run(["rm", "-rf", str(triton_cache)], check=True)
        triton_cache.mkdir(parents=True, exist_ok=True)
        
        logger.info("📥 Cloning SageAttention...")
        subprocess.run([
            "git", "clone", "--depth", "1",
            "https://github.com/thu-ml/SageAttention.git",
            str(build_dir)
        ], check=True, env=env, timeout=120)
        
        # Build with clean environment
        logger.info("🔨 Building SageAttention (with Python 3.12 tokenization fix)...")
        
        result = subprocess.run([
            sys.executable, "-m", "pip", "install",
            "--no-cache-dir",
            "--force-reinstall",  # Important for cache issues
            "."
        ], cwd=str(build_dir), env=env, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            logger.error(f"❌ SageAttention build failed:")
            logger.error(f"STDOUT: {result.stdout}")
            logger.error(f"STDERR: {result.stderr}")
            return False
        else:
            logger.info("✅ SageAttention build succeeded")
            if "DEPRECATION:" in result.stdout:
                logger.info("ℹ️ Deprecation warning shown (this is harmless)")
        
        # Cleanup
        subprocess.run(["rm", "-rf", str(build_dir), str(triton_cache)], check=False)
        
        # Clear triton cache again after build
        clear_triton_cache()
        
        # Verification
        try:
            from sageattention import sageattn
            logger.info("✅ SageAttention Python 3.12 build completed and verified!")
            return True
        except ImportError as e:
            logger.error(f"❌ SageAttention built but import failed: {e}")
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
    """Start ComfyUI server - build SageAttention when job comes in"""
    global comfyui_process, comfyui_initialized
    
    if comfyui_initialized:
        return True
    
    try:
        logger.info("🚀 Starting ComfyUI server (Python 3.12 compatible)...")
        
        # Build SageAttention with cache fixes
        logger.info("🔧 Building SageAttention with Python 3.12 compatibility fixes...")
        if not build_sageattention_with_cache_fix():
            logger.warning("⚠️ SageAttention build failed - will use fallback attention")
            # Don't fail completely, try to continue without SageAttention
        
        # Clear cache one more time before starting ComfyUI
        clear_triton_cache()
        
        # Give it a moment
        time.sleep(3)
        
        # Start ComfyUI
        os.chdir(COMFYUI_PATH)
        
        env = os.environ.copy()
        env.update({
            'CUDA_VISIBLE_DEVICES': '0',
            'PYTHONPATH': f"{COMFYUI_PATH}:{env.get('PYTHONPATH', '')}",
            'PYTHONDONTWRITEBYTECODE': '1',  # Prevent cache issues
            'TRITON_CACHE_DIR': '/tmp/triton_runtime'  # Clean runtime cache
        })
        
        logger.info("🔍 Starting ComfyUI with Python 3.12 fixes...")
        
        comfyui_process = subprocess.Popen([
            sys.executable, "main.py",
            "--listen", "127.0.0.1",
            "--port", "8188",
            "--disable-auto-launch",
            "--disable-metadata"
        ], cwd=COMFYUI_PATH, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait for server
        for i in range(180):
            try:
                response = requests.get(f"http://{COMFYUI_SERVER}/", timeout=5)
                if response.status_code == 200:
                    comfyui_initialized = True
                    logger.info("✅ ComfyUI server started successfully")
                    
                    # Check SageAttention status
                    try:
                        from sageattention import sageattn
                        logger.info("✅ SageAttention working with ComfyUI")
                    except Exception as e:
                        logger.warning(f"⚠️ SageAttention not available: {e}")
                        logger.info("ComfyUI will use fallback attention")
                    
                    return True
            except requests.exceptions.RequestException:
                if comfyui_process.poll() is not None:
                    stdout, stderr = comfyui_process.communicate()
                    logger.error("❌ ComfyUI crashed:")
                    logger.error(f"STDOUT: {stdout.decode()}")
                    logger.error(f"STDERR: {stderr.decode()}")
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
        
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        input_dir = Path(COMFYUI_PATH) / "input"
        input_dir.mkdir(exist_ok=True)
        
        filename = f"{uuid.uuid4()}.jpg"
        image_path = input_dir / filename
        
        image.save(image_path, "JPEG", quality=95)
        logger.info(f"✅ Input image saved: {filename}")
        
        return filename
        
    except Exception as e:
        logger.error(f"❌ Failed to process input image: {str(e)}")
        return None

def customize_workflow(workflow: Dict, params: Dict) -> Dict:
    """Customize workflow with user parameters"""
    try:
        effect = params.get("effect", "ghostrider")
        effect_config = effects_data["effects"].get(effect, effects_data["effects"]["ghostrider"])
        
        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue
                
            class_type = node_data.get("class_type", "")
            inputs = node_data.get("inputs", {})
            
            if class_type == "LoadImage":
                if inputs.get("image") == "PLACEHOLDER_IMAGE":
                    inputs["image"] = params["image_filename"]
                    logger.info(f"✅ Updated LoadImage with: {params['image_filename']}")
            
            elif class_type == "WanVideoTextEncode":
                if inputs.get("positive_prompt") == "PLACEHOLDER_PROMPT":
                    inputs["positive_prompt"] = params.get("prompt", effect_config["prompt"])
                    logger.info(f"✅ Updated positive prompt for effect: {effect}")
                
                if inputs.get("negative_prompt") == "PLACEHOLDER_NEGATIVE_PROMPT":
                    inputs["negative_prompt"] = params.get("negative_prompt", effect_config["negative_prompt"])
                    logger.info(f"✅ Updated negative prompt for effect: {effect}")
            
            elif class_type == "WanVideoLoraSelect":
                if inputs.get("lora_name") == "PLACEHOLDER_LORA":
                    lora_filename = effect_config["lora"]
                    inputs["lora_name"] = lora_filename
                    inputs["lora"] = lora_filename
                    inputs["strength"] = effect_config.get("lora_strength", 1.0)
                    logger.info(f"✅ Updated LoRA: {lora_filename} (strength: {inputs['strength']})")
            
            elif class_type == "WanVideoSampler":
                seed_value = params.get("seed", -1)
                if seed_value == -1:
                    seed_value = int(time.time() * 1000) % (2**31)
                inputs["seed"] = seed_value
                logger.info(f"✅ Updated seed: {seed_value}")
                
                if "steps" in params and params["steps"] != 10:
                    inputs["steps"] = params["steps"]
                if "cfg" in params and params["cfg"] != 6:
                    inputs["cfg"] = params["cfg"]
                if "frames" in params and params["frames"] != 85:
                    inputs["frames"] = params["frames"]
            
            # FALLBACK: If SageAttention failed, disable it in WanVideoModelLoader
            elif class_type == "WanVideoModelLoader":
                try:
                    from sageattention import sageattn
                    # Keep sageattn if available
                    if inputs.get("attention_mode") == "sageattn":
                        logger.info("✅ Using SageAttention for model loading")
                except ImportError:
                    # Disable SageAttention if not available
                    if inputs.get("attention_mode") == "sageattn":
                        inputs["attention_mode"] = "disabled"
                        logger.warning("⚠️ Disabled SageAttention in workflow (Python 3.12 compatibility)")
        
        logger.info(f"✅ Workflow customized for effect: {effect}")
        return workflow
        
    except Exception as e:
        logger.error(f"❌ Error customizing workflow: {str(e)}")
        return workflow

def submit_workflow(workflow: Dict) -> Optional[str]:
    """Submit workflow to ComfyUI"""
    try:
        client_id = str(uuid.uuid4())
        prompt_data = {
            "prompt": workflow,
            "client_id": client_id
        }
        
        response = requests.post(
            f"http://{COMFYUI_SERVER}/prompt",
            json=prompt_data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            prompt_id = result.get("prompt_id")
            logger.info(f"✅ Workflow submitted: {prompt_id}")
            return prompt_id
        else:
            logger.error(f"❌ Failed to submit workflow: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error submitting workflow: {str(e)}")
        return None

def wait_for_completion(prompt_id: str, timeout: int = 600) -> Optional[str]:
    """Wait for workflow completion"""
    try:
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            response = requests.get(f"http://{COMFYUI_SERVER}/history/{prompt_id}", timeout=10)
            
            if response.status_code == 200:
                history = response.json()
                
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    
                    for node_id, output in outputs.items():
                        if "videos" in output:
                            videos = output["videos"]
                            if videos:
                                video_info = videos[0]
                                filename = video_info.get("filename")
                                subfolder = video_info.get("subfolder", "")
                                
                                output_dir = Path(COMFYUI_PATH) / "output"
                                if subfolder:
                                    output_dir = output_dir / subfolder
                                
                                video_path = output_dir / filename
                                if video_path.exists():
                                    logger.info(f"✅ Video generated: {filename}")
                                    return str(video_path)
                    
                    status = history[prompt_id].get("status", {})
                    if status.get("status_str") == "error":
                        error_messages = status.get("messages", [])
                        logger.error(f"❌ Workflow execution failed: {error_messages}")
                        return None
            
            time.sleep(3)
        
        logger.error(f"❌ Timeout waiting for completion: {prompt_id}")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error waiting for completion: {str(e)}")
        return None

def encode_video_to_base64(video_path: str) -> Optional[str]:
    """Convert video file to base64"""
    try:
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        
        video_base64 = base64.b64encode(video_bytes).decode("utf-8")
        video_size_mb = len(video_bytes) / (1024 * 1024)
        logger.info(f"✅ Video encoded to base64 ({video_size_mb:.2f}MB)")
        return video_base64
        
    except Exception as e:
        logger.error(f"❌ Failed to encode video: {str(e)}")
        return None

def handler(job):
    """Main handler function - entry point for RunPod jobs"""
    try:
        logger.info("🎬 Starting AI-Avatarka job processing (Python 3.12 compatible)")
        
        job_input = job.get("input", {})
        
        if not job_input.get("image"):
            return {"error": "No image provided"}
        
        if not comfyui_initialized:
            if not start_comfyui():
                return {"error": "Failed to start ComfyUI"}
        
        if effects_data is None:
            if not load_effects_config():
                return {"error": "Failed to load effects configuration"}
        
        image_filename = process_input_image(job_input["image"])
        if not image_filename:
            return {"error": "Failed to process input image"}
        
        workflow = load_workflow()
        if not workflow:
            return {"error": "Failed to load workflow"}
        
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
    logger.info("ℹ️ Triton cache will be cleared on first job to fix tokenization errors")
    
    load_effects_config()
    
    logger.info("🎯 Starting RunPod serverless worker...")
    logger.info("⏳ Ready for jobs...")
    runpod.serverless.start({"handler": handler})