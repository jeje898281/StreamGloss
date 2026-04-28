from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING, Optional

import numpy as np
import pyaudio
import torch

if TYPE_CHECKING:
    from streamgloss.config import AppConfig

logger = logging.getLogger(__name__)


def int16_to_float32(mono_int16: np.ndarray) -> np.ndarray:
    x = mono_int16.astype(np.float32)
    m = np.abs(x).max()
    if m > 0:
        x *= 1.0 / 32768.0
    return x.squeeze()


class AudioIngestionWorker(threading.Thread):
    """
    Producer: PyAudio capture + Silero VADIterator segmentation.
    Pushes float32 mono numpy arrays (full utterances) to ``out_queue``.
    """

    def __init__(
        self,
        cfg: AppConfig,
        out_queue: "queue.Queue[Optional[np.ndarray]]",
        shutdown: threading.Event,
        name: str = "AudioIngestion",
    ) -> None:
        super().__init__(name=name, daemon=True)
        self._cfg = cfg
        self._out = out_queue
        self._shutdown = shutdown
        self._pyaudio: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None

    def run(self) -> None:
        cfg = self._cfg
        window = cfg.vad_window_samples
        max_samples = int(cfg.sample_rate * cfg.max_utterance_seconds)

        print(f"{cfg.log_prefix} Loading Silero VAD (torch.hub)...")
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
            trust_repo=True,
        )
        _get_ts, _save, _read, VADIterator, _collect = utils
        vad_iterator = VADIterator(
            model,
            threshold=cfg.vad_threshold,
            sampling_rate=cfg.sample_rate,
            min_silence_duration_ms=cfg.vad_min_silence_ms,
            speech_pad_ms=cfg.vad_speech_pad_ms,
        )

        self._pyaudio = pyaudio.PyAudio()
        try:
            self._stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=cfg.sample_rate,
                input=True,
                input_device_index=cfg.input_device_index,
                frames_per_buffer=cfg.pyaudio_frames_per_buffer,
            )
        except Exception:
            self._pyaudio.terminate()
            self._pyaudio = None
            raise

        print(
            f"{cfg.log_prefix} Audio capture on device index {cfg.input_device_index} "
            f"({cfg.sample_rate} Hz, VAD window {window})."
        )

        collecting = False
        buffers: list[np.ndarray] = []

        try:
            while not self._shutdown.is_set():
                try:
                    raw = self._stream.read(window, exception_on_overflow=False)
                except OSError as e:
                    if self._shutdown.is_set():
                        break
                    logger.warning("PyAudio read error: %s", e)
                    continue

                int16 = np.frombuffer(raw, dtype=np.int16)
                if int16.size != window:
                    continue
                f32 = int16_to_float32(int16)
                tensor = torch.from_numpy(f32)

                try:
                    speech_event = vad_iterator(tensor)
                except Exception as e:
                    logger.exception("VAD step failed: %s", e)
                    vad_iterator.reset_states()
                    collecting = False
                    buffers.clear()
                    continue

                if speech_event:
                    if "start" in speech_event:
                        collecting = True
                        buffers = [f32.copy()]
                    elif "end" in speech_event:
                        if collecting:
                            buffers.append(f32.copy())
                            utterance = np.concatenate(buffers, dtype=np.float32)
                            collecting = False
                            buffers.clear()
                            if utterance.size >= cfg.min_utterance_samples:
                                try:
                                    self._out.put(utterance, timeout=2.0)
                                except queue.Full:
                                    logger.warning("Audio queue full; dropping utterance.")
                        else:
                            buffers.clear()
                elif collecting:
                    buffers.append(f32.copy())
                    if sum(b.size for b in buffers) >= max_samples:
                        utterance = np.concatenate(buffers, dtype=np.float32)
                        buffers.clear()
                        collecting = False
                        vad_iterator.reset_states()
                        logger.info("Max utterance length reached; flushing segment.")
                        if utterance.size >= cfg.min_utterance_samples:
                            try:
                                self._out.put(utterance, timeout=2.0)
                            except queue.Full:
                                logger.warning("Audio queue full; dropping utterance.")

        finally:
            self._close_audio()
            try:
                self._out.put(None, timeout=1.0)
            except queue.Full:
                logger.warning("Could not push audio sentinel (queue full).")

    def _close_audio(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pyaudio is not None:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None
