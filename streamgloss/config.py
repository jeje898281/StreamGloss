from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppConfig:
    """Central tuning knobs for hardware and quality."""

    input_device_index: int = 3
    sample_rate: int = 16000
    vad_window_samples: int = 512
    pyaudio_frames_per_buffer: int = 512

    whisper_model_size: str = "small"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_initial_prompt: str = "PUBG, gunfight, scopes, enemies, blue zone."
    whisper_beam_size: int = 5
    whisper_language: Optional[str] = "en"
    whisper_no_speech_threshold: float = 0.45
    whisper_condition_on_previous_text: bool = False
    whisper_vad_filter: bool = False

    vad_threshold: float = 0.55
    vad_min_silence_ms: int = 450
    vad_speech_pad_ms: int = 120
    min_utterance_samples: int = 4000
    max_utterance_seconds: float = 22.0

    ollama_model: str = "llama3"
    ollama_temperature: float = 0.0
    ollama_use_json_format: bool = False
    ollama_num_ctx: int = 0

    audio_queue_maxsize: int = 6
    text_queue_maxsize: int = 16

    log_prefix: str = "[StreamGloss]"

    use_subtitle_overlay: bool = True
    log_translations_to_console: bool = False
    overlay_alpha: float = 0.9
    overlay_topmost: bool = True
    overlay_tw_font_size: int = 20
    overlay_en_font_size: int = 13
    overlay_bg_color: str = "#12151c"
    overlay_width_ratio: float = 0.82
    overlay_margin_bottom_ratio: float = 0.08
    display_queue_maxsize: int = 48

    extra: dict = field(default_factory=dict)
