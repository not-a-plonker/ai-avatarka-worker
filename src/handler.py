"""
AI-Avatarka RunPod Serverless Worker Handler
Transforms images into videos using Wan 2.1 with different effects.
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

def ensure_sageattention():
    """Build SageAttention if not already available (like hearmeman's start.sh)"""
    try:
        from sageattention import sageattn
        logger.info("✅ SageAttention already available")
        return True
    except ImportError:
        logger.info("🔧 Building SageAttention (following hearmeman's approach)...")
        try:
            # Clone and build like hearmeman's start.sh
            subprocess.run([
                "git", "clone", "https://github.com/thu-ml/SageAttention.git", "/tmp/SageAttention"
            ], check=True)
            
            subprocess.run([
                "python", "setup.py", "install"
            ], cwd="/tmp/SageAttention", check=True)
            
            # Install triton like hearmeman does
            subprocess.run([
                "pip", "install", "--no-cache-dir", "triton"
            ], check=True)
            
            # Cleanup
            subprocess.run(["rm", "-rf", "/tmp/SageAttention"])
            
            # Test import
            from sageattention import sageattn
            logger.info("✅ SageAttention built and installed successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to build SageAttention: {e}")
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
    """Start ComfyUI server"""
    global comfyui_process, comfyui_initialized
    
    if comfyui_initialized:
        return True
    
    try:
        logger.info("🚀 Starting ComfyUI server...")
        
        # BUILD SAGEATTENTION FIRST! (This is where it actually needs to happen)
        logger.info("🔧 Ensuring SageAttention is available before ComfyUI startup...")
        if not ensure_sageattention():
            logger.error("❌ Failed to build SageAttention")
            return False
        
        # Give it a moment to settle
        time.sleep(2)
        
        # Debug SageAttention before starting ComfyUI
        logger.info("🔍 Checking SageAttention before ComfyUI startup...")
        try:
            import sageattention
            logger.info(f"✅ SageAttention available at: {sageattention.__file__}")
            from sageattention import sageattn
            logger.info("✅ sageattn import works before ComfyUI")
        except Exception as e:
            logger.error(f"❌ SageAttention NOT available before ComfyUI: {e}")
            return False
        
        # Change to ComfyUI directory
        os.chdir(COMFYUI_PATH)
        
        # Debug environment in ComfyUI directory
        logger.info(f"🔍 Working directory: {os.getcwd()}")
        logger.info(f"🔍 Python executable: {sys.executable}")
        logger.info(f"🔍 PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}")
        
        # Start server process
        comfyui_process = subprocess.Popen([
            sys.executable, "main.py",
            "--listen", "127.0.0.1",
            "--port", "8188",
            "--disable-auto-launch",
            "--disable-metadata"
        ], cwd=COMFYUI_PATH)
        
        # Wait for server to be ready
        for i in range(120):  # Wait up to 2 minutes
            try:
                response = requests.get(f"http://{COMFYUI_SERVER}/", timeout=5)
                if response.status_code == 200:
                    comfyui_initialized = True
                    logger.info("✅ ComfyUI server started successfully")
                    
                    # Debug SageAttention after ComfyUI starts
                    logger.info("🔍 Checking SageAttention after ComfyUI startup...")
                    try:
                        import sageattention
                        logger.info(f"✅ SageAttention still available at: {sageattention.__file__}")
                        from sageattention import sageattn
                        logger.info("✅ sageattn import still works after ComfyUI")
                    except Exception as e:
                        logger.error(f"❌ SageAttention BROKEN after ComfyUI startup: {e}")
                    
                    return True
            except:
                time.sleep(1)
        
        logger.error("❌ Failed to start ComfyUI server - timeout")
        return False
        
    except Exception as e:
        logger.error(f"❌ Error starting ComfyUI server: {str(e)}")
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
        # Handle data URL format
        if image_data.startswith("data:image"):
            image_data = image_data.split(",")[1]
        
        # Decode base64 image
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # Save to ComfyUI input directory
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
        
        # Work with API format: {node_id: {inputs: {}, class_type: ""}}
        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue
                
            class_type = node_data.get("class_type", "")
            inputs = node_data.get("inputs", {})
            
            # Update LoadImage node (Node 18) - replace PLACEHOLDER_IMAGE
            if class_type == "LoadImage":
                if inputs.get("image") == "PLACEHOLDER_IMAGE":
                    inputs["image"] = params["image_filename"]
                    logger.info(f"✅ Updated LoadImage with: {params['image_filename']}")
            
            # Update WanVideoTextEncode (Node 16) - replace prompts
            elif class_type == "WanVideoTextEncode":
                if inputs.get("positive_prompt") == "PLACEHOLDER_PROMPT":
                    inputs["positive_prompt"] = params.get("prompt", effect_config["prompt"])
                    logger.info(f"✅ Updated positive prompt for effect: {effect}")
                
                if inputs.get("negative_prompt") == "PLACEHOLDER_NEGATIVE_PROMPT":
                    inputs["negative_prompt"] = params.get("negative_prompt", effect_config["negative_prompt"])
                    logger.info(f"✅ Updated negative prompt for effect: {effect}")
            
            # Update WanVideoLoraSelect (Node 41) - replace PLACEHOLDER_LORA
            elif class_type == "WanVideoLoraSelect":
                if inputs.get("lora_name") == "PLACEHOLDER_LORA":
                    lora_filename = effect_config["lora"]
                    inputs["lora_name"] = lora_filename
                    inputs["lora"] = lora_filename  # Set both inputs to the same filename
                    inputs["strength"] = effect_config.get("lora_strength", 1.0)
                    logger.info(f"✅ Updated LoRA: {lora_filename} (strength: {inputs['strength']})")
            
            # Update WanVideoSampler (Node 27) - handle seed properly
            elif class_type == "WanVideoSampler":
                # Handle seed - use random if -1
                seed_value = params.get("seed", -1)
                if seed_value == -1:
                    seed_value = int(time.time() * 1000) % (2**31)  # Generate random seed
                inputs["seed"] = seed_value
                logger.info(f"✅ Updated seed: {seed_value}")
                
                # Update other sampler parameters if provided
                if "steps" in params and params["steps"] != 10:
                    inputs["steps"] = params["steps"]
                    
                if "cfg" in params and params["cfg"] != 6:
                    inputs["cfg"] = params["cfg"]
                    
                if "frames" in params and params["frames"] != 85:
                    inputs["frames"] = params["frames"]
        
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
                    
                    # Look for video output from VHS_VideoCombine node (Node 30)
                    for node_id, output in outputs.items():
                        if "videos" in output:
                            videos = output["videos"]
                            if videos:
                                video_info = videos[0]
                                filename = video_info.get("filename")
                                subfolder = video_info.get("subfolder", "")
                                
                                # Construct full path
                                output_dir = Path(COMFYUI_PATH) / "output"
                                if subfolder:
                                    output_dir = output_dir / subfolder
                                
                                video_path = output_dir / filename
                                if video_path.exists():
                                    logger.info(f"✅ Video generated: {filename}")
                                    return str(video_path)
                    
                    # Check if execution failed
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
        logger.info("🎬 Starting AI-Avatarka job processing")
        
        # Get job input
        job_input = job.get("input", {})
        
        # Validate required inputs
        if not job_input.get("image"):
            return {"error": "No image provided"}
        
        # Initialize ComfyUI if needed
        if not comfyui_initialized:
            if not start_comfyui():
                return {"error": "Failed to start ComfyUI"}
        
        # Load effects config if needed
        if effects_data is None:
            if not load_effects_config():
                return {"error": "Failed to load effects configuration"}
        
        # Process input image
        image_filename = process_input_image(job_input["image"])
        if not image_filename:
            return {"error": "Failed to process input image"}
        
        # Load workflow
        workflow = load_workflow()
        if not workflow:
            return {"error": "Failed to load workflow"}
        
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
        
        # Encode video to base64
        video_base64 = encode_video_to_base64(video_path)
        if not video_base64:
            return {"error": "Failed to encode output video"}
        
        # Clean up input image
        try:
            input_path = Path(COMFYUI_PATH) / "input" / image_filename
            if input_path.exists():
                input_path.unlink()
                logger.info("✅ Cleaned up input image")
        except:
            pass
        
        # Return success response
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
    logger.info("🚀 Initializing AI-Avatarka Worker...")
    
    # Build SageAttention FIRST, before anything else (like hearmeman's start.sh)
    if not ensure_sageattention():
        logger.error("❌ Failed to ensure SageAttention - worker may not function correctly")
        # Continue anyway, maybe it will work
    else:
        # Give it a moment to settle and verify it's really available
        time.sleep(2)
        try:
            from sageattention import sageattn
            logger.info("✅ SageAttention build completed and verified working")
        except Exception as e:
            logger.error(f"❌ SageAttention build completed but import still fails: {e}")
            logger.error("This will likely cause ComfyUI startup to fail")
    
    # Load effects configuration
    load_effects_config()
    
    # Start the serverless worker (ComfyUI will be started on first job)
    runpod.serverless.start({"handler": handler})