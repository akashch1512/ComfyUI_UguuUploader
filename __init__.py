import os
import requests
from typing import Dict, Any, Tuple
import folder_paths

# Correct Uguu.se API endpoint for file uploads
UGUU_UPLOAD_URL = "https://uguu.se/upload"

class UguuUploader:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),  # Accept VIDEO input from ComfyUI
            },
            "optional": {
                "output_format": ("STRING", {"default": "text"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("uguu_link",)
    FUNCTION = "upload_video"
    CATEGORY = "File Upload"

    def upload_video(self, video: Any, output_format: str = "text") -> Tuple[str]:
        """
        Upload a VIDEO input from ComfyUI to Uguu.se and return the public link.
        """
        # Extract video file path from ComfyUI VIDEO object
        print(f"[UguuUploader] DEBUG: video type = {type(video)}, value = {video}")
        
        video_file_path = None
        
        # Handle VideoFromFile object (comfy_api.latest._input_impl.video_types.VideoFromFile)
        if hasattr(video, 'video_path'):
            video_file_path = video.video_path
        elif hasattr(video, 'path'):
            video_file_path = video.path
        elif hasattr(video, 'file_path'):
            video_file_path = video.file_path
        # Try to get attributes if it's an object
        elif hasattr(video, '__dict__'):
            attrs = video.__dict__
            print(f"[UguuUploader] DEBUG: Object attributes = {attrs}")
            # Check for private attribute __file (mangled to _VideoFromFile__file)
            video_file_path = attrs.get('_VideoFromFile__file') or attrs.get('_video__file') or attrs.get('video_path') or attrs.get('path') or attrs.get('file_path') or attrs.get('_video_path') or attrs.get('_path')
        # Handle string path
        elif isinstance(video, str):
            video_file_path = video
        # Handle dictionary
        elif isinstance(video, dict):
            video_file_path = video.get("video_path") or video.get("path") or video.get("filename")
        # Handle tuple/list format
        elif isinstance(video, (tuple, list)) and len(video) > 0:
            video_filename = video[0]
            if isinstance(video_filename, str):
                if not os.path.isabs(video_filename):
                    video_file_path = os.path.join(folder_paths.get_output_directory(), video_filename)
                else:
                    video_file_path = video_filename
        
        if not video_file_path:
            print(f"[UguuUploader] ERROR: Could not extract video file path")
            return ("Error: Could not extract video file path from input",)
        
        print(f"[UguuUploader] DEBUG: Extracted video_file_path = {video_file_path}")

        if not os.path.exists(video_file_path):
            print(f"[UguuUploader] Error: Video file not found at {video_file_path}")
            return ("Error: file not found",)

        try:
            with open(video_file_path, "rb") as f:
                # Uguu expects the file field name to be files[] — send filename and file object
                files = {
                    "files[]": (os.path.basename(video_file_path), f)
                }
                params = {"output": output_format} if output_format else None
                print(f"[UguuUploader] Uploading to {UGUU_UPLOAD_URL} with params {params}")
                resp = requests.post(UGUU_UPLOAD_URL, files=files, params=params, timeout=60)
            
            print(f"[UguuUploader] DEBUG: Response status = {resp.status_code}")
            print(f"[UguuUploader] DEBUG: Response headers = {resp.headers}")
            print(f"[UguuUploader] DEBUG: Response text = {resp.text[:200]}")
            
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            response_text = resp.text.strip()
            
            # If response is empty, return error
            if not response_text:
                print(f"[UguuUploader] Error: Empty response from Uguu.se")
                return ("Error: Empty response from Uguu.se",)
            
            # Try JSON first
            uploaded_link = None
            if "application/json" in content_type:
                try:
                    data = resp.json()
                    # try common shapes: string, dict with url, list of files, etc.
                    if isinstance(data, str):
                        uploaded_link = data.strip()
                    elif isinstance(data, dict):
                        # look for common keys
                        uploaded_link = data.get("url") or data.get("file") or data.get("link") or str(data)
                    elif isinstance(data, list) and data:
                        first = data[0]
                        if isinstance(first, str):
                            uploaded_link = first
                        elif isinstance(first, dict):
                            uploaded_link = first.get("url") or first.get("file") or str(first)
                        else:
                            uploaded_link = str(first)
                    else:
                        uploaded_link = str(data)
                except Exception as e:
                    print(f"[UguuUploader] Failed to parse JSON: {e}, using raw text")
                    uploaded_link = response_text
            else:
                # non-json: return raw text (often Uguu returns the direct url as plain text)
                uploaded_link = response_text

            print(f"[UguuUploader] Upload successful: {uploaded_link}")
            return (uploaded_link,)

        except requests.exceptions.RequestException as e:
            print(f"[UguuUploader] Network/HTTP error: {e}")
            return (f"HTTP Error: {e}",)
        except Exception as e:
            print(f"[UguuUploader] Unexpected error: {e}")
            return (f"Error: {e}",)


# Node mapping for whatever system you use
NODE_CLASS_MAPPINGS = {
    "UguuUploader": UguuUploader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UguuUploader": "🚀 Uguu.se Video Uploader",
}
