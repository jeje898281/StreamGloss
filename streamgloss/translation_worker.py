from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING, Any, Optional

import ollama
from ollama import ResponseError

from streamgloss.translation_cleaner import extract_translation

if TYPE_CHECKING:
    from streamgloss.config import AppConfig

logger = logging.getLogger(__name__)


TRANSLATION_SYSTEM = (
    "You are a machine that ONLY outputs compact JSON. "
    "No markdown, no code fences, no explanations, no keys other than specified."
)


def build_translation_prompt(source_text: str) -> str:
    return f"""Task: translate English live stream speech to Taiwan Traditional Chinese.

Output format: exactly one JSON object on one line, with a single key "translation".
Value must be the translated string only. No other keys. No preamble.

Examples:
Input: Watch the ridge, two knocks on the left.
Output: {{"translation":"注意山脊，左邊有兩個腳步聲。"}}

Input: I'm rotating wide, need meds.
Output: {{"translation":"我要大繞一下，需要補品。"}}

Input: {source_text!r}
Output:"""


class TranslationWorker(threading.Thread):
    """Consumer 2: English transcript → Ollama → printed Traditional Chinese."""

    def __init__(
        self,
        cfg: AppConfig,
        text_queue: "queue.Queue[Optional[str]]",
        shutdown: threading.Event,
        display_queue: "Optional[queue.Queue[Optional[dict[str, str]]]]" = None,
        name: str = "Translation",
    ) -> None:
        super().__init__(name=name, daemon=True)
        self._cfg = cfg
        self._text_q = text_queue
        self._shutdown = shutdown
        self._display_q = display_queue

    def _push_ui_error(self, source_en: str, detail: str) -> None:
        if self._display_q is None:
            return
        short = detail if len(detail) < 220 else detail[:217] + "…"
        try:
            self._display_q.put_nowait(
                {
                    "en": source_en,
                    "tw": "",
                    "error": f"翻譯失敗：{short}",
                }
            )
        except queue.Full:
            pass

    def _ollama_options(self) -> dict[str, Any]:
        cfg = self._cfg
        opts: dict[str, Any] = {"temperature": cfg.ollama_temperature}
        if cfg.ollama_num_ctx > 0:
            opts["num_ctx"] = int(cfg.ollama_num_ctx)
        return opts

    def _generate(self, client: ollama.Client, prompt: str, use_json: bool) -> str:
        cfg = self._cfg
        kwargs: dict[str, Any] = {
            "model": cfg.ollama_model,
            "system": TRANSLATION_SYSTEM,
            "prompt": prompt,
            "stream": False,
            "options": self._ollama_options(),
        }
        if use_json:
            kwargs["format"] = "json"
        resp = client.generate(**kwargs)
        return (getattr(resp, "response", None) or "").strip()

    def run(self) -> None:
        cfg = self._cfg
        client = ollama.Client()
        while True:
            try:
                text = self._text_q.get(timeout=0.5)
            except queue.Empty:
                if self._shutdown.is_set():
                    break
                continue

            if text is None:
                break

            prompt = build_translation_prompt(text)
            try:
                use_json = cfg.ollama_use_json_format
                raw = self._generate(client, prompt, use_json=use_json)
                cleaned = extract_translation(raw)
                if not cleaned and use_json:
                    raw = self._generate(client, prompt, use_json=False)
                    cleaned = extract_translation(raw)
            except ResponseError as e:
                err = str(e)
                mem_hint = "memory" in err.lower() or "記憶體" in err or "GiB" in err
                if mem_hint:
                    tip = (
                        f"{cfg.log_prefix} Ollama 記憶體不足：載入模型 {cfg.ollama_model!r} 需要比目前可用更多的系統 RAM。"
                        f" 請先關閉其他大型程式（例如遊戲、吃記憶體的瀏覽器分頁）再試；仍不足時才考慮在 config 改較小模型。"
                        f" 詳情：{err}"
                    )
                    logger.warning(tip)
                    print(tip, flush=True)
                else:
                    msg = f"{cfg.log_prefix} Ollama API 錯誤（{e.status_code}）：{err}"
                    logger.warning(msg)
                    print(msg, flush=True)
                self._push_ui_error(text, err)
                continue
            except Exception as e:
                msg = f"{cfg.log_prefix} Ollama 呼叫失敗（請確認服務已開、且模型 {cfg.ollama_model!r} 已拉取）：{e}"
                logger.exception(msg)
                print(msg, flush=True)
                self._push_ui_error(text, str(e))
                continue

            if cleaned:
                if self._display_q is not None:
                    try:
                        self._display_q.put({"en": text, "tw": cleaned}, timeout=1.0)
                    except queue.Full:
                        logger.warning("字幕佇列已滿，略過一則更新。")
                if cfg.log_translations_to_console or self._display_q is None:
                    print(f"\n{cfg.log_prefix} [EN] {text}")
                    print(f"{cfg.log_prefix} [TW] {cleaned}")
                    print("-" * 48)
            else:
                snippet = (raw[:400] + "…") if len(raw) > 400 else raw
                warn = f"{cfg.log_prefix} 翻譯結果為空（模型回覆無法解析）。raw 片段: {snippet!r}"
                logger.warning(warn)
                print(warn, flush=True)
