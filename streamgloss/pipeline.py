from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

from faster_whisper import WhisperModel

from streamgloss.audio_ingestion import AudioIngestionWorker
from streamgloss.config import AppConfig
from streamgloss.transcription_worker import TranscriptionWorker
from streamgloss.translation_worker import TranslationWorker

logger = logging.getLogger(__name__)


class StreamGlossPipeline:
    """
    Wires audio → STT → translation queues with graceful shutdown.
    """

    def __init__(
        self,
        cfg: Optional[AppConfig] = None,
        display_queue: Optional["queue.Queue[Optional[dict[str, str]]]"] = None,
    ) -> None:
        self.cfg = cfg or AppConfig()
        self._shutdown = threading.Event()
        self._stop_done = threading.Lock()
        self._stopped = False
        self._bootstrapped = False
        self._display_q = display_queue
        self._audio_q: queue.Queue[Optional[object]] = queue.Queue(
            maxsize=self.cfg.audio_queue_maxsize
        )
        self._text_q: queue.Queue[Optional[str]] = queue.Queue(
            maxsize=self.cfg.text_queue_maxsize
        )
        self._whisper: Optional[WhisperModel] = None
        self._ingest: Optional[AudioIngestionWorker] = None
        self._stt: Optional[TranscriptionWorker] = None
        self._translate: Optional[TranslationWorker] = None

    def _bootstrap(self) -> None:
        if self._bootstrapped:
            return
        self._bootstrapped = True
        cfg = self.cfg
        print(f"{cfg.log_prefix} Initializing Faster-Whisper ({cfg.whisper_model_size}) on {cfg.whisper_device}...")
        self._whisper = WhisperModel(
            cfg.whisper_model_size,
            device=cfg.whisper_device,
            compute_type=cfg.whisper_compute_type,
        )

        try:
            import ollama as _ollama

            _ollama.Client().show(cfg.ollama_model)
            print(f"{cfg.log_prefix} Ollama 模型 {cfg.ollama_model!r} 已就緒。")
        except Exception as e:
            print(
                f"{cfg.log_prefix} 警告：無法連線 Ollama 或找不到模型 {cfg.ollama_model!r}。"
                f"翻譯會失敗。詳情：{e}",
                flush=True,
            )

        self._translate = TranslationWorker(
            cfg,
            self._text_q,
            self._shutdown,
            display_queue=self._display_q,
        )
        self._stt = TranscriptionWorker(
            cfg,
            self._whisper,
            self._audio_q,
            self._text_q,
            self._shutdown,
        )
        self._ingest = AudioIngestionWorker(cfg, self._audio_q, self._shutdown)

        self._translate.start()
        self._stt.start()
        self._ingest.start()

        print(f"{cfg.log_prefix} Pipeline running.", flush=True)

    def run_forever(self, block_on_interrupt: bool = True) -> None:
        self._bootstrap()
        if not block_on_interrupt:
            while not self._shutdown.is_set():
                time.sleep(0.25)
            return
        print(f"{self.cfg.log_prefix} Ctrl+C to stop.", flush=True)
        try:
            while True:
                time.sleep(0.25)
        except KeyboardInterrupt:
            print(f"\n{self.cfg.log_prefix} Shutdown requested...", flush=True)
        finally:
            self.stop()

    def stop(self) -> None:
        with self._stop_done:
            if self._stopped:
                return
            self._stopped = True
        self._shutdown.set()

        if self._ingest is not None and self._ingest.is_alive():
            self._ingest.join(timeout=15.0)
            if self._ingest.is_alive():
                logger.warning("Audio ingestion thread did not finish in time.")

        if self._stt is not None and self._stt.is_alive():
            self._stt.join(timeout=180.0)
            if self._stt.is_alive():
                logger.warning("Transcription thread did not finish in time.")

        if self._translate is not None and self._translate.is_alive():
            self._translate.join(timeout=180.0)
            if self._translate.is_alive():
                logger.warning("Translation thread did not finish in time.")

        self._whisper = None
        if self._display_q is not None:
            try:
                self._display_q.put_nowait(None)
            except queue.Full:
                pass
        print(f"{self.cfg.log_prefix} Resources released (Whisper model dropped).", flush=True)
