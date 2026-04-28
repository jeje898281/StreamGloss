from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING, Optional

import numpy as np
from faster_whisper import WhisperModel

if TYPE_CHECKING:
    from streamgloss.config import AppConfig

logger = logging.getLogger(__name__)


class TranscriptionWorker(threading.Thread):
    """Consumer 1: utterance audio → text → ``text_queue``."""

    def __init__(
        self,
        cfg: AppConfig,
        model: WhisperModel,
        audio_queue: "queue.Queue[Optional[np.ndarray]]",
        text_queue: "queue.Queue[Optional[str]]",
        shutdown: threading.Event,
        name: str = "Transcription",
    ) -> None:
        super().__init__(name=name, daemon=True)
        self._cfg = cfg
        self._model = model
        self._audio_q = audio_queue
        self._text_q = text_queue
        self._shutdown = shutdown

    def run(self) -> None:
        cfg = self._cfg
        while True:
            try:
                item = self._audio_q.get(timeout=0.5)
            except queue.Empty:
                if self._shutdown.is_set():
                    break
                continue

            if item is None:
                break

            try:
                segments, info = self._model.transcribe(
                    item,
                    language=cfg.whisper_language,
                    beam_size=cfg.whisper_beam_size,
                    initial_prompt=cfg.whisper_initial_prompt,
                    no_speech_threshold=cfg.whisper_no_speech_threshold,
                    condition_on_previous_text=cfg.whisper_condition_on_previous_text,
                    vad_filter=cfg.whisper_vad_filter,
                )
                text = "".join(s.text for s in segments).strip()
            except Exception as e:
                logger.exception("Whisper transcribe failed: %s", e)
                continue

            if not text:
                dur = float(item.shape[0]) / float(cfg.sample_rate)
                logger.info(
                    "Whisper 無文字（可能被 no_speech 濾掉或純噪音），約 %.2fs，language=%s",
                    dur,
                    getattr(info, "language", None),
                )
                continue

            try:
                self._text_q.put(text, timeout=5.0)
            except queue.Full:
                logger.warning("Text queue full; dropping transcript.")

        try:
            self._text_q.put(None, timeout=2.0)
        except queue.Full:
            logger.warning("Could not push text sentinel.")
