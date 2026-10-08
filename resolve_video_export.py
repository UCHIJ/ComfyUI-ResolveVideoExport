import os
from fractions import Fraction

import numpy as np
import torch
import folder_paths

try:
    import av  # PyAV: ships with ComfyUI (used by its core video nodes), bundles its own FFmpeg
except ImportError:
    av = None

try:
    import comfy.model_management
    import comfy.utils
    _HAS_COMFY = True
except ImportError:  # allows standalone testing outside ComfyUI
    _HAS_COMFY = False


# ==============================================================================
# Presets (single source of truth for both nodes and the encoder)
# ==============================================================================
PRESETS = {
    "DNxHR HQ (8-bit, High Quality)": {
        "codec": "dnxhd", "profile": "dnxhr_hq", "pix_fmt": "yuv422p", "high_bit": False},
    "DNxHR HQX (10-bit, High Quality)": {
        "codec": "dnxhd", "profile": "dnxhr_hqx", "pix_fmt": "yuv422p10le", "high_bit": True},
    "DNxHR SQ (8-bit, Standard Quality)": {
        "codec": "dnxhd", "profile": "dnxhr_sq", "pix_fmt": "yuv422p", "high_bit": False},
    "DNxHR LB (8-bit, Low Bandwidth)": {
        "codec": "dnxhd", "profile": "dnxhr_lb", "pix_fmt": "yuv422p", "high_bit": False},
    "ProRes 422 HQ": {
        "codec": "prores_ks", "profile": "hq", "pix_fmt": "yuv422p10le", "high_bit": True},
    "ProRes 422 Standard": {
        "codec": "prores_ks", "profile": "standard", "pix_fmt": "yuv422p10le", "high_bit": True},
    "ProRes 422 LT": {
        "codec": "prores_ks", "profile": "lt", "pix_fmt": "yuv422p10le", "high_bit": True},
}
PRESET_NAMES = list(PRESETS.keys())
DEFAULT_PREFIX = "video/Resolve_Export"

AUDIO_CHUNK_MAX = 16384


# ==============================================================================
# Helpers
# ==============================================================================
def _to_fraction(fps):
    """Exact rational frame rate; snaps 23.976 / 29.97 / 59.94 etc. to their true NTSC values."""
    if isinstance(fps, Fraction):
        return fps
    fps = float(fps)
    for base in (24, 30, 48, 60, 120):
        ntsc = Fraction(base * 1000, 1001)
        if abs(fps - float(ntsc)) < 0.005:
            return ntsc
    return Fraction(fps).limit_denominator(1000)


def _to_numpy(x):
    if isinstance(x, torch.Tensor):
        return x.detach().cpu().numpy()
    return np.asarray(x)


def _prepare_audio(audio, duration):
    """
    ComfyUI AUDIO ({'waveform': [B,C,S], 'sample_rate': int}) -> interleaved int16 [S, C],
    trimmed to the video duration. More than 2 channels are reduced to the first two.
    """
    waveform = _to_numpy(audio["waveform"])
    if waveform.ndim == 3:
        waveform = waveform[0]
    waveform = waveform[:2]
    sample_rate = int(audio["sample_rate"])
    samples = min(waveform.shape[1], int(round(duration * sample_rate)))
    pcm = np.rint(np.clip(waveform[:, :samples], -1.0, 1.0) * 32767.0).astype(np.int16)
    return np.ascontiguousarray(pcm.T), waveform.shape[0], sample_rate


def _frame_to_array(frame, high_bit, pad_h, pad_w):
    frame = np.clip(_to_numpy(frame), 0.0, 1.0)
    if high_bit:
        arr = np.rint(frame * 65535.0).astype("<u2")  # rgb48le
    else:
        arr = np.rint(frame * 255.0).astype(np.uint8)  # rgb24
    if pad_h or pad_w:
        arr = np.pad(arr, ((0, pad_h), (0, pad_w), (0, 0)))  # zero = black
    return np.ascontiguousarray(arr)


def make_output_path(filename_prefix, output_dir, width, height):
    """
    Resolve the save location. Any subfolder in the prefix (e.g. 'video/Resolve_Export')
    is created automatically and must stay inside ComfyUI's output directory.
    """
    full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
        filename_prefix, output_dir, width, height
    )
    file_name = f"{filename}_{counter:05d}_.mov"
    return os.path.join(full_output_folder, file_name), file_name, subfolder


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ==============================================================================
# Core encoder (PyAV)
# ==============================================================================
def encode_video_file(output_path, images, fps, codec_preset, audio=None):
    """Encode an IMAGE batch (+ optional AUDIO) to a ProRes / DNxHR .mov."""
    if av is None:
        raise RuntimeError(
            "PyAV ('av') is not installed. Update ComfyUI, or run `pip install av` "
            "in ComfyUI's Python environment."
        )

    cfg = PRESETS[codec_preset]
    num_frames, height, width, channels = images.shape
    if channels < 3:
        raise ValueError(f"Expected an RGB image batch, got {channels} channel(s).")
    images = images[..., :3]  # drop alpha if present

    if cfg["codec"] == "dnxhd" and (width < 256 or height < 120):
        raise ValueError(
            f"DNxHR requires frames of at least 256x120 (got {width}x{height}). "
            "Upscale the images or choose a ProRes preset."
        )

    rate = _to_fraction(fps)
    time_base = 1 / rate
    pad_w, pad_h = width % 2, height % 2  # 4:2:2 needs even dimensions
    out_w, out_h = width + pad_w, height + pad_h
    in_fmt = "rgb48le" if cfg["high_bit"] else "rgb24"  # 10-bit presets get 16-bit input

    pcm = None
    if (
        isinstance(audio, dict)
        and audio.get("waveform") is not None
        and audio["waveform"].shape[-1] > 0
    ):
        pcm, audio_channels, sample_rate = _prepare_audio(audio, float(num_frames / rate))
        layout = "mono" if audio_channels == 1 else "stereo"

    container = av.open(output_path, mode="w", format="mov")
    try:
        vstream = container.add_stream(cfg["codec"], rate=rate)
        vstream.width = out_w
        vstream.height = out_h
        vstream.pix_fmt = cfg["pix_fmt"]
        options = {
            "profile": cfg["profile"],
            "colorspace": "bt709",
            "color_primaries": "bt709",
            "color_trc": "bt709",
            "color_range": "tv",
        }
        if cfg["codec"] == "prores_ks":
            options["vendor"] = "apl0"  # Apple vendor tag, best compatibility
        vstream.options = options

        astream = None
        if pcm is not None:
            astream = container.add_stream("pcm_s16le", rate=sample_rate)
            astream.layout = layout

        # RGB -> BT.709 limited-range YUV (matches ffmpeg's `scale` + `format` filters)
        graph = av.filter.Graph()
        src = graph.add_buffer(width=out_w, height=out_h, format=in_fmt, time_base=time_base)
        scale = graph.add("scale", "out_color_matrix=bt709:out_range=tv")
        fmt = graph.add("format", cfg["pix_fmt"])
        sink = graph.add("buffersink")
        src.link_to(scale)
        scale.link_to(fmt)
        fmt.link_to(sink)
        graph.configure()

        def drain_video():
            while True:
                try:
                    out_frame = graph.pull()
                except (BlockingIOError, EOFError):
                    return
                container.mux(vstream.encode(out_frame))

        audio_pos = 0

        def mux_audio_until(target):
            nonlocal audio_pos
            while audio_pos < target:
                end = min(target, audio_pos + AUDIO_CHUNK_MAX)
                chunk = pcm[audio_pos:end].reshape(1, -1)  # packed s16: (1, samples * channels)
                aframe = av.AudioFrame.from_ndarray(chunk, format="s16", layout=layout)
                aframe.sample_rate = sample_rate
                aframe.pts = audio_pos
                aframe.time_base = Fraction(1, sample_rate)
                container.mux(astream.encode(aframe))
                audio_pos = end

        pbar = comfy.utils.ProgressBar(num_frames) if _HAS_COMFY else None
        for i in range(num_frames):
            if _HAS_COMFY:
                comfy.model_management.throw_exception_if_processing_interrupted()

            arr = _frame_to_array(images[i], cfg["high_bit"], pad_h, pad_w)
            vframe = av.VideoFrame.from_ndarray(arr, format=in_fmt)
            vframe.pts = i
            vframe.time_base = time_base
            graph.push(vframe)
            drain_video()

            if astream is not None:
                last = i == num_frames - 1
                target = pcm.shape[0] if last else int(i + 1) * sample_rate * rate.denominator // rate.numerator
                mux_audio_until(min(target, pcm.shape[0]))
            if pbar:
                pbar.update(1)

        graph.push(None)  # flush filter graph
        drain_video()
        container.mux(vstream.encode(None))  # flush encoders
        if astream is not None:
            container.mux(astream.encode(None))
        container.close()
    except BaseException as exc:
        try:
            container.close()
        except Exception:
            pass
        _remove_quietly(output_path)
        if isinstance(exc, (ValueError, RuntimeError)) or not isinstance(exc, Exception):
            raise
        raise RuntimeError(f"Encoding failed: {exc}") from exc


# ==============================================================================
# Node 1: VIDEO input exporter
# ==============================================================================
class DaVinciResolveVideoExporter:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
                "filename_prefix": ("STRING", {"default": DEFAULT_PREFIX}),
                "codec_preset": (PRESET_NAMES, {"default": PRESET_NAMES[0]}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("filepath",)
    FUNCTION = "encode_video"
    OUTPUT_NODE = True
    CATEGORY = "Export"

    def encode_video(self, video, filename_prefix, codec_preset):
        components = video.get_components()
        images = components.images
        fps = components.frame_rate
        audio = components.audio

        if images is None or images.shape[0] == 0:
            raise ValueError("[ResolveVideoExporter] The VIDEO input contains no frames.")

        _, height, width, _ = images.shape
        output_path, _, _ = make_output_path(filename_prefix, self.output_dir, width, height)

        encode_video_file(output_path, images, fps, codec_preset, audio)

        print(f"[ResolveVideoExporter] Exported VIDEO to: {output_path}")
        return {"result": (output_path,)}


# ==============================================================================
# Node 2: IMAGE batch (+ optional AUDIO) exporter
# ==============================================================================
class DaVinciResolveImageExporter:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.001}),
                "filename_prefix": ("STRING", {"default": DEFAULT_PREFIX}),
                "codec_preset": (PRESET_NAMES, {"default": PRESET_NAMES[0]}),
            },
            "optional": {
                "audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("filepath",)
    FUNCTION = "encode_images"
    OUTPUT_NODE = True
    CATEGORY = "Export"

    def encode_images(self, images, fps, filename_prefix, codec_preset, audio=None):
        if images.shape[0] == 0:
            raise ValueError("[ResolveImageExporter] The IMAGE input contains no frames.")

        _, height, width, _ = images.shape
        output_path, _, _ = make_output_path(filename_prefix, self.output_dir, width, height)

        encode_video_file(output_path, images, fps, codec_preset, audio)

        print(f"[ResolveImageExporter] Exported IMAGES to: {output_path}")
        return {"result": (output_path,)}