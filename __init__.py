import os
import io
import uuid
import tempfile
import requests
from typing import Any, Tuple
import folder_paths  # required for getting the output directory

UGUU_UPLOAD_URL = "https://uguu.se/upload"

class UguuUploader:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
            },
            "optional": {
                "output_format": ("STRING", {"default": "text"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("uguu_link",)
    FUNCTION = "upload_video"
    CATEGORY = "File Upload"

    def _log(self, *args):
        print("[UguuUploader]", *args)

    def _write_bytes_to_temp(self, data: bytes, suffix=".mp4") -> str:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(data)
        tmp.close()
        return tmp.name

    def _try_call_save_to(self, obj, target_path) -> bool:
        """
        Special-case handler for objects that implement `save_to(target_path)`
        or `save_to(path=...)` semantics (e.g. VideoFromComponents).
        """
        save_meth = getattr(obj, "save_to", None)
        if callable(save_meth):
            try:
                # try positional
                save_meth(target_path)
                self._log("Used save_to(positional) to write to", target_path)
                return True
            except TypeError:
                try:
                    save_meth(path=target_path)
                    self._log("Used save_to(path=...) to write to", target_path)
                    return True
                except TypeError:
                    try:
                        save_meth(filename=target_path)
                        self._log("Used save_to(filename=...) to write to", target_path)
                        return True
                    except Exception as e:
                        self._log("save_to exists but calls failed:", e)
            except Exception as e:
                self._log("Exception when calling save_to:", e)
        return False

    def _handle_get_stream_source(self, obj, tmp_path_base) -> str | None:
        """
        Handle objects exposing get_stream_source(), which may return:
        - a file path string
        - a file-like object with read()
        - raw bytes
        - an iterable of bytes/chunks
        """
        getter = getattr(obj, "get_stream_source", None)
        if not callable(getter):
            return None
        try:
            src = getter()
            self._log("get_stream_source() returned:", type(src))
            # string path
            if isinstance(src, str) and os.path.exists(src):
                return os.path.abspath(src)
            # bytes
            if isinstance(src, (bytes, bytearray)):
                return self._write_bytes_to_temp(src, suffix=".mp4")
            # file-like with read()
            if hasattr(src, "read") and callable(getattr(src, "read")):
                try:
                    data = src.read()
                    if isinstance(data, (bytes, bytearray)):
                        return self._write_bytes_to_temp(data, suffix=".mp4")
                    # if read returns iterable chunks
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                    for chunk in data:
                        tmp.write(chunk)
                    tmp.close()
                    return tmp.name
                except Exception as e:
                    self._log("Error reading get_stream_source() file-like:", e)
            # iterable of bytes
            try:
                it = iter(src)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                wrote = False
                for chunk in it:
                    if isinstance(chunk, (bytes, bytearray)):
                        tmp.write(chunk)
                        wrote = True
                    else:
                        # ignore non-bytes
                        pass
                tmp.close()
                if wrote:
                    return tmp.name
            except TypeError:
                pass
        except Exception as e:
            self._log("Exception calling get_stream_source():", e)
        return None

    def _handle_get_components(self, obj) -> str | None:
        """
        Try obj.get_components() -> inspect returned structure for paths or bytes.
        """
        getter = getattr(obj, "get_components", None)
        if not callable(getter):
            return None
        try:
            comps = getter()
            self._log("get_components() returned type", type(comps))
            # if it's dict-like or has attributes, try same heuristics
            if isinstance(comps, dict):
                for key in ("video_path", "path", "file_path", "filename", "output_path"):
                    v = comps.get(key)
                    if isinstance(v, str) and os.path.exists(v):
                        return os.path.abspath(v)
                    if isinstance(v, (bytes, bytearray)):
                        return self._write_bytes_to_temp(v, suffix=".mp4")
            # if object with attrs
            if hasattr(comps, "__dict__"):
                for key in ("video_path", "path", "file_path", "filename", "output_path"):
                    v = getattr(comps, key, None)
                    if isinstance(v, str) and os.path.exists(v):
                        return os.path.abspath(v)
                    if isinstance(v, (bytes, bytearray)):
                        return self._write_bytes_to_temp(v, suffix=".mp4")
            # fallback: if comps has method to export stream
            get_stream = getattr(comps, "get_stream_source", None)
            if callable(get_stream):
                return self._handle_get_stream_source(comps, tempfile.gettempdir())
        except Exception as e:
            self._log("Exception while handling get_components():", e)
        return None

    def upload_video(self, video: Any, output_format: str = "text") -> Tuple[str]:
        self._log("DEBUG: Received video input:", type(video), repr(video))

        video_file_path = None
        temp_to_cleanup = []

        # 1) tuple/list like (filename, subfolder,...)
        if isinstance(video, (tuple, list)):
            try:
                if len(video) >= 1 and isinstance(video[0], str):
                    video_filename = video[0]
                    video_subfolder = video[1] if len(video) >= 2 and isinstance(video[1], str) else ""
                    try:
                        full_output_dir = folder_paths.get_output_directory()
                    except Exception:
                        full_output_dir = None
                    if full_output_dir:
                        if video_subfolder:
                            candidate = os.path.join(full_output_dir, video_subfolder, video_filename)
                        else:
                            candidate = os.path.join(full_output_dir, video_filename)
                        if os.path.exists(candidate):
                            video_file_path = os.path.abspath(candidate)
                            self._log("Parsed tuple/list ->", video_file_path)
                        else:
                            # still record path for debug
                            video_file_path = os.path.abspath(candidate)
                            self._log("Parsed tuple/list (file not present yet) ->", video_file_path)
            except Exception as e:
                self._log("Error parsing tuple/list:", e)

        # 2) direct string
        if not video_file_path and isinstance(video, str):
            video_file_path = os.path.abspath(video)
            self._log("Video is a string path:", video_file_path)

        # 3) dict-like
        if not video_file_path:
            try:
                if isinstance(video, dict):
                    for k in ("video_path", "path", "file_path", "filename"):
                        v = video.get(k)
                        if isinstance(v, str) and os.path.exists(v):
                            video_file_path = os.path.abspath(v)
                            self._log("Found path in dict ->", video_file_path)
                            break
                        if isinstance(v, (bytes, bytearray)):
                            p = self._write_bytes_to_temp(v, suffix=".mp4")
                            temp_to_cleanup.append(p)
                            video_file_path = p
                            self._log("Wrote bytes from dict to temp ->", video_file_path)
                            break
            except Exception as e:
                self._log("Error inspecting dict-like:", e)

        # 4) check save_to (explicit for VideoFromComponents)
        if not video_file_path:
            try:
                # create a path to attempt export
                try:
                    export_target = os.path.join(folder_paths.get_output_directory(), f"uguu_export_{uuid.uuid4().hex}.mp4")
                except Exception:
                    export_target = os.path.join(tempfile.gettempdir(), f"uguu_export_{uuid.uuid4().hex}.mp4")
                ok = self._try_call_save_to(video, export_target)
                if ok and os.path.exists(export_target):
                    video_file_path = os.path.abspath(export_target)
                    temp_to_cleanup.append(video_file_path)
                    self._log("Exported via save_to ->", video_file_path)
                elif ok:
                    # save_to reported success but file missing — still keep path for debug
                    video_file_path = os.path.abspath(export_target)
                    temp_to_cleanup.append(video_file_path)
                    self._log("save_to called but file not found at expected path ->", video_file_path)
            except Exception as e:
                self._log("Exception when trying save_to:", e)

        # 5) try get_stream_source()
        if not video_file_path:
            try:
                tmp = self._handle_get_stream_source(video, tempfile.gettempdir())
                if tmp:
                    video_file_path = tmp
                    temp_to_cleanup.append(video_file_path)
                    self._log("Resolved via get_stream_source ->", video_file_path)
            except Exception as e:
                self._log("Error handling get_stream_source:", e)

        # 6) try get_components()
        if not video_file_path:
            try:
                tmp = self._handle_get_components(video)
                if tmp:
                    video_file_path = tmp
                    temp_to_cleanup.append(video_file_path)
                    self._log("Resolved via get_components ->", video_file_path)
            except Exception as e:
                self._log("Error handling get_components:", e)

        # 7) fallback attributes & file-like
        if not video_file_path:
            # attrs and getattr
            try:
                cand_attrs = {}
                if hasattr(video, "__dict__"):
                    cand_attrs.update(video.__dict__)
                for attr in ("video_path", "path", "file_path", "filename", "output_path", "outpath", "file"):
                    val = cand_attrs.get(attr) if attr in cand_attrs else getattr(video, attr, None)
                    if isinstance(val, str) and os.path.exists(val):
                        video_file_path = os.path.abspath(val)
                        self._log(f"Found attribute '{attr}' ->", video_file_path)
                        break
                    if isinstance(val, (bytes, bytearray)):
                        p = self._write_bytes_to_temp(val, suffix=".mp4")
                        temp_to_cleanup.append(p)
                        video_file_path = p
                        self._log(f"Wrote raw bytes attr '{attr}' to temp ->", video_file_path)
                        break
            except Exception as e:
                self._log("Error checking attributes:", e)

        if not video_file_path and hasattr(video, "read") and callable(getattr(video, "read")):
            try:
                data = video.read()
                if isinstance(data, (bytes, bytearray)):
                    p = self._write_bytes_to_temp(data, suffix=".mp4")
                    temp_to_cleanup.append(p)
                    video_file_path = p
                    self._log("Wrote file-like to temp ->", video_file_path)
                else:
                    # iterable chunks
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                    wrote = False
                    for chunk in data:
                        if isinstance(chunk, (bytes, bytearray)):
                            tmp.write(chunk)
                            wrote = True
                    tmp.close()
                    if wrote:
                        temp_to_cleanup.append(tmp.name)
                        video_file_path = tmp.name
                        self._log("Wrote iterable chunks to temp ->", video_file_path)
            except Exception as e:
                self._log("Error reading file-like object:", e)

        # If still unresolved, return inspection info
        if not video_file_path:
            # produce concise inspection: attributes and callables
            try:
                attrs = video.__dict__ if hasattr(video, "__dict__") else {}
                callables = [n for n in dir(video) if not n.startswith("__") and callable(getattr(video, n))]
                debug = {"attrs": {k: type(v).__name__ for k, v in attrs.items()}, "callables_sample": callables[:30]}
            except Exception as e:
                debug = {"inspect_error": str(e)}
            self._log("ERROR: Could not extract video file path. Inspection:", debug)
            return (f"Error: Could not extract video file path from input. Inspection: {debug}",)

        video_file_path = os.path.abspath(video_file_path)
        self._log("Final resolved video_file_path =", video_file_path)

        if not os.path.exists(video_file_path):
            parent_dir = os.path.dirname(video_file_path)
            if os.path.exists(parent_dir):
                try:
                    contents = os.listdir(parent_dir)
                except Exception:
                    contents = "<could not list directory>"
                self._log(f"Video file not found. Parent dir '{parent_dir}' contents:", contents)
            else:
                self._log(f"Video file not found. Parent directory '{parent_dir}' does not exist.")
            for p in temp_to_cleanup:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
            return (f"Error: file not found at {video_file_path}",)

        # upload
        try:
            with open(video_file_path, "rb") as f:
                files = {"files[]": (os.path.basename(video_file_path), f)}
                params = {"output": output_format or "text"}
                self._log(f"Uploading to {UGUU_UPLOAD_URL} with params {params}")
                resp = requests.post(UGUU_UPLOAD_URL, files=files, params=params, timeout=120)

            self._log("Response status =", resp.status_code)
            self._log("Response headers =", resp.headers)
            text_preview = (resp.text[:1000] + "...") if len(resp.text) > 1000 else resp.text
            self._log("Response text preview =", text_preview)

            resp.raise_for_status()
            uploaded_link = None
            response_text = resp.text.strip()

            if "application/json" in resp.headers.get("Content-Type", ""):
                try:
                    data = resp.json()
                    if isinstance(data, dict) and "files" in data and isinstance(data["files"], list) and data["files"]:
                        first_file = data["files"][0]
                        uploaded_link = first_file.get("url") or first_file.get("link") or str(first_file)
                    elif isinstance(data, str) and data.startswith("http"):
                        uploaded_link = data
                    else:
                        uploaded_link = str(data)
                except Exception as e:
                    self._log("Failed to parse JSON:", e)
                    uploaded_link = response_text
            else:
                uploaded_link = response_text

            if not uploaded_link or not isinstance(uploaded_link, str):
                self._log("WARNING: Extracted link does not look like a URL. Raw response:", response_text)

            # cleanup temp files if any
            for p in temp_to_cleanup:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

            return (uploaded_link if uploaded_link else "Error: empty or invalid upload response",)

        except requests.exceptions.RequestException as e:
            error_message = f"HTTP Error: {e}"
            if getattr(e, "response", None) is not None:
                try:
                    error_message += f" - Response: {e.response.text[:200]}"
                except Exception:
                    pass
            self._log("Network/HTTP error:", error_message)
            return (error_message,)

        except Exception as e:
            self._log("Unexpected error:", e)
            return (f"Error: {e}",)

# Node mappings
NODE_CLASS_MAPPINGS = {
    "UguuUploader": UguuUploader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UguuUploader": "🚀 Uguu.se Video Uploader",
}
