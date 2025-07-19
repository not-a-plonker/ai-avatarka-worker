"""
AI-Avatarka RunPod Serverless Worker Handler
Fixed to use venv Python and download models at startup like hearmeman
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

# Constants - Use base image paths
COMFYUI_PATH = "/workspace/ComfyUI"
COMFYUI_SERVER = "127.0.0.1:8188"
EFFECTS_CONFIG = "/workspace/prompts/effects.json"
WORKFLOW_PATH = "/workspace/workflow/universal_i2v.json"

# Global state
comfyui_process = None
comfyui_initialized = False
effects_data = None
models_downloaded = False

def clear_triton_cache():
    """Clear triton cache to fix Python 3.12 tokenization errors"""
    try:
        logger.info("🧹 Clearing triton cache (Python 3.12 fix)...")
        
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

def download_models_and_loras():
    """Download models and LoRAs using the dedicated download script"""
    global models_downloaded
    
    if models_downloaded:
        return True
        
    try:
        logger.info("🔧 Running model download script...")
        
        # Run the dedicated download script
        result = subprocess.run([
            sys.executable, "/workspace/builder/download_models.py"
        ], capture_output=True, text=True, timeout=3600)  # 1 hour timeout
        
        if result.returncode == 0:
            logger.info("✅ Model download script completed successfully")
            models_downloaded = True
            return True
        else:
            logger.error(f"❌ Model download script failed:")
            logger.error(f"STDOUT: {result.stdout}")
            logger.error(f"STDERR: {result.stderr}")
            return False
        
    except subprocess.TimeoutExpired:
        logger.error("❌ Model download script timed out")
        return False
    except Exception as e:
        logger.error(f"❌ Error running model download script: {e}")
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
    """Start ComfyUI with --use-sage-attention flag using venv Python"""
    global comfyui_process, comfyui_initialized
    
    if comfyui_initialized:
        return True
    
    try:
        logger.info("🚀 Starting ComfyUI with venv Python...")
        
        # Clear triton cache
        clear_triton_cache()
        time.sleep(2)
        
        # Change to ComfyUI directory
        os.chdir(COMFYUI_PATH)
        
        # Set environment like hearmeman's script
        env = os.environ.copy()
        env.update({
            'CUDA_VISIBLE_DEVICES': '0',
            'PYTHONPATH': f"{COMFYUI_PATH}:{env.get('PYTHONPATH', '')}",
            'PYTHONDONTWRITEBYTECODE': '1',
            'TRITON_CACHE_DIR': '/tmp/triton_runtime'
        })
        
        # CRITICAL: Use venv Python where SageAttention is installed
        cmd = [
            "/opt/venv/bin/python", "main.py",
            "--listen", "127.0.0.1",
            "--port", "8188", 
            "--use-sage-attention"
        ]
        
        logger.info("🚀 Starting ComfyUI WITH --use-sage-attention (venv Python)")
        logger.info(f"🔍 ComfyUI command: {' '.join(cmd)}")
        logger.info(f"📁 Working directory: {os.getcwd()}")
        
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
        
        # Wait for ComfyUI to start
        logger.info("⏳ Waiting for ComfyUI to start...")
        for attempt in range(60):  # 60 seconds timeout
            try:
                response = requests.get(f"http://{COMFYUI_SERVER}/", timeout=2)
                if response.status_code == 200:
                    logger.info("✅ ComfyUI started successfully!")
                    comfyui_initialized = True
                    return True
            except requests.RequestException:
                pass
            
            # Check if process crashed
            if comfyui_process.poll() is not None:
                stdout, stderr = comfyui_process.communicate()
                logger.error(f"❌ ComfyUI process crashed:")
                logger.error(f"Exit code: {comfyui_process.returncode}")
                logger.error(f"Output: {stdout}")
                return False
            
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
        
        # Save to ComfyUI input directory
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
        effect_config = effects_data.get(params['effect'], {})
        
        # Update workflow nodes based on your workflow structure
        for node_id, node in workflow.items():
            node_type = node.get("class_type", "")
            
            # Update image input node
            if node_type == "LoadImage":
                if "inputs" in node:
                    node["inputs"]["image"] = params["image_filename"]
            
            # Update sampling parameters
            elif node_type == "KSampler":
                if "inputs" in node:
                    node["inputs"]["steps"] = params.get("steps", 10)
                    node["inputs"]["cfg"] = params.get("cfg", 6)
                    node["inputs"]["seed"] = params.get("seed", -1)
            
            # Update text prompts
            elif node_type == "CLIPTextEncode":
                if "inputs" in node and "text" in node["inputs"]:
                    # Use custom prompt or effect default
                    if params.get("prompt"):
                        node["inputs"]["text"] = params["prompt"]
                    elif effect_config.get("prompt"):
                        node["inputs"]["text"] = effect_config["prompt"]
            
            # Update LoRA loader for effect
            elif node_type == "LoraLoader":
                if "inputs" in node and effect_config.get("lora_name"):
                    node["inputs"]["lora_name"] = effect_config["lora_name"]
            
            # Update video parameters
            elif node_type in ["VideoLinearCFGGuidance", "VHS_VideoCombine"]:
                if "inputs" in node:
                    if "frame_rate" in node["inputs"]:
                        node["inputs"]["frame_rate"] = params.get("fps", 16)
                    if "frames" in node["inputs"]:
                        node["inputs"]["frames"] = params.get("frames", 85)
        
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

def wait_for_completion(prompt_id: str, timeout: int = 300) -> Optional[str]:
    """Wait for workflow completion and return output path"""
    try:
        start_time = time.time()
        
        while time.time() - start_time < timeout:
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

def initialize_worker():
    """Initialize worker - download models and LoRAs at startup"""
    try:
        logger.info("🚀 Initializing AI-Avatarka Worker...")
        
        # Run the dedicated download script
        if not download_models_and_loras():
            logger.error("❌ Failed to download required models and LoRAs")
            return False
        
        # Load effects configuration
        if not load_effects_config():
            logger.warning("⚠️ Effects config not loaded - using defaults")
        
        logger.info("✅ Worker initialization complete")
        return True
        
    except Exception as e:
        logger.error(f"❌ Worker initialization failed: {e}")
        return False

def handler(job):
    """Main RunPod handler"""
    try:
        logger.info("🎬 Processing job...")
        
        # Initialize worker on first job (download models, etc.)
        if not models_downloaded:
            if not initialize_worker():
                return {"error": "Worker initialization failed"}
        
        # Start ComfyUI if not already running
        if not start_comfyui():
            return {"error": "Failed to start ComfyUI"}
        
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
        
        logger.info(f"🎭 Processing effect: {params['effect']}")
        
        # Customize workflow
        workflow = customize_workflow(workflow, params)
        
        # Submit workflow
        prompt_id = submit_workflow(workflow)
        if not prompt_id:
            return {"error": "Failed to submit workflow"}
        
        # Wait for completion
        video_path = wait_for_completion(prompt_id)
        if not video_path:
            return {"error": "Video generation failed or timed out"}
        
        # Encode result
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
    logger.info("🚀 Starting AI-Avatarka Worker...")
    logger.info("✅ Using hearmeman base image with SageAttention pre-installed") 
    logger.info("🔧 Will download models at startup like hearmeman")
    
    logger.info("🎯 Starting RunPod serverless worker...")
    runpod.serverless.start({"handler": handler})