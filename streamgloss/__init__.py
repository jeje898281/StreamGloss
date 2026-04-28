"""StreamGloss: real-time ingest → STT → local LLM translation pipeline."""

from streamgloss.pipeline import StreamGlossPipeline
from streamgloss.subtitle_overlay import run_subtitle_app

__all__ = ["StreamGlossPipeline", "run_subtitle_app"]
