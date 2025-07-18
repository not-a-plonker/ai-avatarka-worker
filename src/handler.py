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

def build_sageattention_in_comfyui_startup():
    """Build SageAttention when ComfyUI starts (CRITICAL: This runs when job comes in)"""
    try:
        # First check if already available
        try:
            from sageattention import sageattn
            logger.info("✅ SageAttention already available, skipping build")
            return True
        except ImportError:
            pass
        
        logger.info("🔧 Building SageAttention (triggered by job start)...")
        
        # Set environment variables for compilation
        env = os.environ.copy()
        env.update({
            'TORCH_CUDA_ARCH_LIST': '8.6;8.9;9.0',
            'CUDA_VISIBLE_DEVICES': '0',
            'MAX_JOBS': '4',
            'NINJA_STATUS': '[%f/%t] '
        })
        
        # Create temp build directory
        build_dir = Path("/tmp/sageattention_runtime_build")
        if build_dir.exists():
            subprocess.run(["rm", "-rf", str(build_dir)], check=True)
        
        logger.info("📥 Cloning SageAttention for runtime build...")
        subprocess.run([
            "git", "clone", "--depth", "1",
            "https://github.com/thu-ml/SageAttention.git",
            str(build_dir)
        ], check=True, env=env, timeout=120)
        
        # Use modern pip wheel build (avoids deprecated egg installation)
        logger.info("🔨 Building SageAttention wheel (modern method)...")
        
        # Step 1: Build wheel
        wheel_result = subprocess.run([
            sys.executable, "-m", "pip", "wheel",
            "--no-cache-dir",
            "--no-deps",  # Don't reinstall existing deps
            "--wheel-dir", "/tmp/wheels",
            "."
        ], cwd=str(build_dir), env=env, capture_output=True, text=True, timeout=600)
        
        if wheel_result.returncode != 0:
            logger.warning("⚠️ Wheel build failed, trying direct install...")
            logger.warning(f"Wheel STDERR: {wheel_result.stderr}")
            
            # Fallback: direct pip install
            direct_result = subprocess.run([
                sys.executable, "-m", "pip", "install",
                "--no-cache-dir",
                "--force-reinstall",
                "."
            ], cwd=str(build_dir), env=env, capture_output=True, text=True, timeout=600)
            
            if direct_result.returncode != 0:
                logger.error(f"❌ Direct install also failed:")
                logger.error(f"STDOUT: {direct_result.stdout}")
                logger.error(f"STDERR: {direct_result.stderr}")
                return False
            else:
                logger.info("✅ Direct install succeeded")
        else:
            # Step 2: Install the built wheel
            logger.info("🎯 Installing built wheel...")
            wheel_files = list(Path("/tmp/wheels").glob("sageattention*.whl"))
            
            if wheel_files:
                install_result = subprocess.run([
                    sys.executable, "-m", "pip", "install",
                    "--no-cache-dir",
                    "--force-reinstall",
                    str(wheel_files[0])
                ], env=env, capture_output=True, text=True, timeout=120)
                
                if install_result.returncode != 0:
                    logger.error(f"❌ Wheel install failed: {install_result.stderr}")
                    return False
                else:
                    logger.info("✅ Wheel install succeeded")
            else:
                logger.error("❌ No wheel file found after build")
                return False
        
        # Cleanup
        subprocess.run(["rm", "-rf", str(build_dir), "/tmp/wheels"], check=False)
        
        # Critical verification
        try:
            from sageattention import sageattn
            logger.info("✅ SageAttention runtime build completed and verified!")
            return True
        except ImportError as e:
            logger.error(f"❌ SageAttention built but import still fails: {e}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("❌ SageAttention runtime build timed out")
        return False
    except Exception as e:
        logger.error(f"❌ SageAttention runtime build error: {e}")
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
    """Start ComfyUI server - THIS IS WHERE SAGEATTENTION BUILDS WHEN JOB COMES IN"""
    global comfyui_process, comfyui_initialized
    
    if comfyui_initialized:
        return True
    
    try:
        logger.info("🚀 Starting ComfyUI server (job triggered)...")
        
        # CRITICAL: Build SageAttention NOW when job comes in
        logger.info("🔧 Building SageAttention at job start (this is the right time!)...")
        if not build_sageattention_in_comfyui_startup():
            logger.error("❌ SageAttention build failed - ComfyUI may not work")
            # Continue anyway, maybe it will work without SageAttention
        else:
            logger.info("✅ SageAttention successfully built when job started")
        
        # Give SageAttention a moment to settle
        time.sleep(2)
        
        # Final verification before starting ComfyUI
        try:
            from sageattention import sageattn
            logger.info("✅ SageAttention verified and ready for ComfyUI")
        except ImportError as e:
            logger.warning(f"⚠️ SageAttention not available for ComfyUI: {e}")
            logger.warning("ComfyUI will try to start anyway...")
        
        # Change to ComfyUI directory
        os.chdir(COMFYUI_PATH)
        
        # Set environment for ComfyUI startup
        env = os.environ.copy()
        env.update({
            'CUDA_VISIBLE_DEVICES': '0',
            'PYTHONPATH': f"{COMFYUI_PATH}:{env.get('PYTHONPATH', '')}",
            'TORCH_CUDA_ARCH_LIST': '8.6;8.9;9.0'
        })
        
        logger.info(f"🔍 Starting ComfyUI from: {os.getcwd()}")
        
        # Start ComfyUI server process
        comfyui_process = subprocess.Popen([
            sys.executable, "main.py",
            "--listen", "127.0.0.1",
            "--port", "8188",
            "--disable-auto-launch",
            "--disable-metadata"
        ], cwd=COMFYUI_PATH, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait for server to be ready with better error reporting
        for i in range(180):  # Wait up to 3 minutes
            try:
                response = requests.get(f"http://{COMFYUI_SERVER}/", timeout=5)
                if response.status_code == 200:
                    comfyui_initialized = True
                    logger.info("✅ ComfyUI server started successfully")
                    
                    # Final SageAttention status check
                    try:
                        from sageattention import sageattn
                        logger.info("✅ SageAttention working with ComfyUI")
                    except Exception as e:
                        logger.warning(f"⚠️ SageAttention status after ComfyUI start: {e}")
                    
                    return True
            except requests.exceptions.RequestException:
                # Check if ComfyUI process crashed
                if comfyui_process.poll() is not None:
                    stdout, stderr = comfyui_process.communicate()
                    logger.error("❌ ComfyUI process crashed during startup:")
                    logger.error(f"STDOUT: {stdout.decode()}")
                    logger.error(f"STDERR: {stderr.decode()}")
                    return False
                
                time.sleep(1)
        
        logger.error("❌ ComfyUI server startup timeout")
        
        # Get process output for debugging
        if comfyui_process.poll() is None:
            comfyui_process.terminate()
            try:
                stdout, stderr = comfyui_process.communicate(timeout=10)
                logger.error(f"ComfyUI STDOUT: {stdout.decode()}")
                logger.error(f"ComfyUI STDERR: {stderr.decode()}")
            except subprocess.TimeoutExpired:
                comfyui_process.kill()
        
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
        
        # Initialize ComfyUI if needed (includes SageAttention build)
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
    
    # DO NOT BUILD SAGEATTENTION HERE - it must happen in start_comfyui() when job comes in
    logger.info("ℹ️ SageAttention will be built when first job arrives")
    
    # Load effects configuration
    load_effects_config()
    
    # Start the serverless worker (ComfyUI will be started on first job)
    logger.info("🎯 Starting RunPod serverless worker...")
    logger.info("⏳ Waiting for jobs... (SageAttention will build on first job)")
    runpod.serverless.start({"handler": handler})