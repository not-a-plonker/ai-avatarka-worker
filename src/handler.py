"""
AI-Avatarka RunPod Serverless Worker Handler
Fixed to use venv Python with build-time model downloads
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
sage_attention_available = False

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

def test_sage_attention():
   """Test if SageAttention is available and working"""
   try:
       logger.info("🔍 Testing SageAttention availability...")
       
       # Test basic import
       import sageattention
       logger.info("✅ SageAttention import successful")
       
       # Test version info
       try:
           version = getattr(sageattention, '__version__', 'unknown')
           logger.info(f"📦 SageAttention version: {version}")
       except:
           logger.info("📦 SageAttention version: unknown")
       
       # Test CUDA availability for SageAttention
       import torch
       if torch.cuda.is_available():
           logger.info(f"🎮 CUDA available: {torch.version.cuda}")
           logger.info(f"🎮 GPU: {torch.cuda.get_device_name(0)}")
           
           # Test basic SageAttention functionality
           try:
               # Create small test tensors
               device = torch.device('cuda:0')
               q = torch.randn(1, 8, 64, 64, dtype=torch.float16, device=device)
               k = torch.randn(1, 8, 64, 64, dtype=torch.float16, device=device)
               v = torch.randn(1, 8, 64, 64, dtype=torch.float16, device=device)
               
               # Test sage attention call
               output = sageattention.sageattn(q, k, v)
               logger.info("✅ SageAttention CUDA test successful")
               return True
               
           except Exception as e:
               logger.warning(f"⚠️ SageAttention CUDA test failed: {e}")
               return False
       else:
           logger.warning("⚠️ CUDA not available for SageAttention")
           return False
           
   except ImportError as e:
       logger.warning(f"⚠️ SageAttention not available: {e}")
       return False
   except Exception as e:
       logger.error(f"❌ SageAttention test error: {e}")
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
   """Start ComfyUI using venv Python with SageAttention if available"""
   global comfyui_process, comfyui_initialized, sage_attention_available
   
   if comfyui_initialized:
       return True
   
   try:
       logger.info("🚀 Starting ComfyUI with venv Python...")
       
       # Test SageAttention first
       sage_attention_available = test_sage_attention()
       
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
       
       # Use SageAttention if available
       if sage_attention_available:
           cmd = [
               "/opt/venv/bin/python", "main.py",
               "--listen", "127.0.0.1",
               "--port", "8188",
               "--use-sage-attention"
           ]
           logger.info("🚀 Starting ComfyUI with SageAttention ENABLED")
       else:
           cmd = [
               "/opt/venv/bin/python", "main.py",
               "--listen", "127.0.0.1",
               "--port", "8188"
           ]
           logger.info("🚀 Starting ComfyUI with SageAttention DISABLED (fallback)")
       
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
       effect_config = effects_data.get(params['effect'], {}) if effects_data else {}
       
       # Update workflow nodes based on WanVideo workflow structure
       for node_id, node in workflow.items():
           node_type = node.get("class_type", "")
           
           # Update image input node (LoadImage)
           if node_type == "LoadImage":
               if "inputs" in node:
                   node["inputs"]["image"] = params["image_filename"]
           
           # Update LoRA selection
           elif node_type == "WanVideoLoraSelect":
               if "inputs" in node:
                   lora_name = effect_config.get("lora_name", f"{params['effect']}.safetensors")
                   node["inputs"]["lora_name"] = lora_name
                   node["inputs"]["lora"] = lora_name  # Both fields need the same value
           
           # Update text prompts (WanVideoTextEncode)
           elif node_type == "WanVideoTextEncode":
               if "inputs" in node:
                   # Use custom prompt or effect default
                   positive_prompt = params.get("prompt", effect_config.get("prompt", ""))
                   negative_prompt = params.get("negative_prompt", effect_config.get("negative_prompt", ""))
                   
                   node["inputs"]["positive_prompt"] = positive_prompt
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
           
           # Handle attention mode based on SageAttention availability
           elif node_type == "WanVideoModelLoader":
               if "inputs" in node:
                   if sage_attention_available:
                       node["inputs"]["attention_mode"] = "sageattn"
                       logger.info("🎯 Using SageAttention mode")
                   else:
                       node["inputs"]["attention_mode"] = "sdpa"
                       logger.info("🎯 Using SDPA mode (SageAttention unavailable)")
       
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

def wait_for_completion(prompt_id: str, timeout: int = None) -> Optional[str]:
   """Wait for workflow completion and return output path"""
   try:
       start_time = time.time()
       
       while True:
           try:
               # Check if timeout specified and exceeded
               if timeout:
                   elapsed = time.time() - start_time
                   if elapsed > timeout:
                       logger.error(f"❌ Timeout after {elapsed:.0f} seconds")
                       return None
               
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
   """Check GPU memory usage"""
   try:
       import torch
       if torch.cuda.is_available():
           memory_allocated = torch.cuda.memory_allocated(0) / 1024**3  # GB
           memory_cached = torch.cuda.memory_reserved(0) / 1024**3      # GB
           logger.info(f"🔍 GPU Memory - Allocated: {memory_allocated:.1f}GB, Cached: {memory_cached:.1f}GB")
       else:
           logger.warning("⚠️ CUDA not available")
   except Exception as e:
       logger.warning(f"⚠️ Could not check GPU memory: {e}")

def handler(job):
   """Main RunPod handler"""
   try:
       logger.info("🎬 Processing job...")
       
       # Check GPU memory at start
       check_gpu_memory()
       
       # Load effects config if not loaded
       if not effects_data and not load_effects_config():
           logger.warning("⚠️ Effects config not loaded - using defaults")
       
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
           "sage_attention_used": sage_attention_available
       }
       
   except Exception as e:
       logger.error(f"❌ Handler error: {str(e)}")
       return {"error": f"Processing failed: {str(e)}"}

# Initialize on startup
if __name__ == "__main__":
   logger.info("🚀 Starting AI-Avatarka Worker...")
   logger.info("✅ Models downloaded during Docker build")
   logger.info("🔧 Testing SageAttention availability and ComfyUI startup")
   
   logger.info("🎯 Starting RunPod serverless worker...")
   runpod.serverless.start({"handler": handler})