import os
import requests

# Correct Uguu.se API endpoint for file uploads
UGUU_UPLOAD_URL = "https://uguu.se/upload"

class UguuUploader:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_file_path": ("STRING", {"forceInput": True}),  # full path to the video file
            },
            "optional": {
                # add optional params if needed
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("uguu_link",)
    FUNCTION = "upload_video"
    CATEGORY = "File Upload"

    def upload_video(self, video_file_path, output_format: str = "text"):
        """
        Upload a single file to Uguu.se and return the public link (string).
        `output_format` can be one of: json, csv, text, html, gyazo.
        Default set to 'text' to get the raw URL back; use 'json' if you prefer structured response.
        """
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
                resp = requests.post(UGUU_UPLOAD_URL, files=files, params=params, timeout=60)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            # If JSON response, try to extract sensible value
            if "application/json" in content_type:
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
            else:
                # non-json: return raw text (often Uguu returns the direct url as plain text)
                uploaded_link = resp.text.strip()

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
