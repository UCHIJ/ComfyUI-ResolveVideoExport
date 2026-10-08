from .resolve_video_export import (
    DaVinciResolveVideoExporter,
    DaVinciResolveImageExporter,
)
NODE_CLASS_MAPPINGS = {
    "DaVinciResolveVideoExporter": DaVinciResolveVideoExporter,
    "DaVinciResolveImageExporter": DaVinciResolveImageExporter,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DaVinciResolveVideoExporter": "DaVinci Resolve Export (VIDEO)",
    "DaVinciResolveImageExporter": "DaVinci Resolve Export (IMAGE + AUDIO)",
}
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]