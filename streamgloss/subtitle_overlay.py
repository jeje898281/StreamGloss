from __future__ import annotations

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any, Callable, Optional

from streamgloss.config import AppConfig


class SubtitleOverlay:
    """
    置頂半透明字幕視窗：EN / TW 分行顯示；可調透明度、字級、置頂；拖曳深灰標題列可移動視窗。
    """

    def __init__(
        self,
        cfg: AppConfig,
        message_queue: "queue.Queue[Optional[dict[str, str]]]",
        on_close: Callable[[], None],
    ) -> None:
        self._cfg = cfg
        self._q = message_queue
        self._on_close = on_close
        self._offset_x = 0
        self._offset_y = 0

        self.root = tk.Tk()
        self.root.title("StreamGloss 字幕")
        self.root.minsize(480, 160)
        self._alpha = float(cfg.overlay_alpha)
        self.root.attributes("-alpha", self._alpha)
        self.root.attributes("-topmost", cfg.overlay_topmost)

        bg = cfg.overlay_bg_color
        self.root.configure(bg=bg)

        title_bar = tk.Frame(self.root, bg="#2a2a2a", height=28, cursor="fleur")
        title_bar.pack(fill=tk.X, side=tk.TOP)
        title_bar.bind("<ButtonPress-1>", self._on_press)
        title_bar.bind("<B1-Motion>", self._on_motion)
        tk.Label(
            title_bar,
            text=" StreamGloss · 拖曳此列移動 ",
            bg="#2a2a2a",
            fg="#bbbbbb",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=4)

        self._body = tk.Frame(self.root, bg=bg)
        self._body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 4))

        self._tw_var = tk.StringVar(value="（等待翻譯…）")
        self._en_var = tk.StringVar(value="")

        self._tw_font = tkfont.Font(family="Microsoft JhengHei", size=cfg.overlay_tw_font_size, weight="bold")
        self._en_font = tkfont.Font(family="Consolas", size=cfg.overlay_en_font_size)

        self._lbl_tw = tk.Label(
            self._body,
            textvariable=self._tw_var,
            bg=bg,
            fg="#f5f5f5",
            font=self._tw_font,
            justify=tk.LEFT,
            wraplength=780,
            anchor="nw",
        )
        self._lbl_tw.pack(fill=tk.BOTH, expand=True, anchor="nw")

        self._lbl_en = tk.Label(
            self._body,
            textvariable=self._en_var,
            bg=bg,
            fg="#9aa0a6",
            font=self._en_font,
            justify=tk.LEFT,
            wraplength=780,
            anchor="w",
        )
        self._lbl_en.pack(fill=tk.X, anchor="w", pady=(4, 0))

        ctl = tk.Frame(self.root, bg="#252525")
        ctl.pack(fill=tk.X, side=tk.BOTTOM, pady=(0, 6), padx=8)

        tk.Label(ctl, text="透明度", bg="#252525", fg="#cccccc", font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        self._scale_alpha = ttk.Scale(
            ctl,
            from_=0.25,
            to=1.0,
            orient=tk.HORIZONTAL,
            command=self._on_alpha_change,
            length=200,
        )
        self._scale_alpha.set(self._alpha)
        self._scale_alpha.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=(0, 4))
        ctl.grid_columnconfigure(1, weight=1)
        ctl.grid_columnconfigure(3, weight=1)

        tk.Label(ctl, text="中文字級", bg="#252525", fg="#cccccc", font=("Segoe UI", 9)).grid(
            row=1, column=0, sticky="w"
        )
        self._scale_tw = ttk.Scale(
            ctl,
            from_=14,
            to=36,
            orient=tk.HORIZONTAL,
            command=self._on_tw_font_change,
            length=140,
        )
        self._scale_tw.set(float(cfg.overlay_tw_font_size))
        self._scale_tw.grid(row=1, column=1, sticky="ew", padx=4)

        tk.Label(ctl, text="英文字級", bg="#252525", fg="#cccccc", font=("Segoe UI", 9)).grid(
            row=1, column=2, padx=(12, 0)
        )
        self._scale_en = ttk.Scale(
            ctl,
            from_=10,
            to=24,
            orient=tk.HORIZONTAL,
            command=self._on_en_font_change,
            length=140,
        )
        self._scale_en.set(float(cfg.overlay_en_font_size))
        self._scale_en.grid(row=1, column=3, sticky="ew", padx=4)

        row2 = tk.Frame(ctl, bg="#252525")
        row2.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        self._top_var = tk.BooleanVar(value=cfg.overlay_topmost)
        ttk.Checkbutton(row2, text="置頂", variable=self._top_var, command=self._toggle_topmost).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        ttk.Button(row2, text="清除字幕", command=self._clear_text).pack(side=tk.LEFT, padx=4)
        ttk.Button(row2, text="結束（關閉管線）", command=self._close).pack(side=tk.LEFT, padx=12)

        self.root.bind("<Configure>", self._on_resize)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(int(sw * cfg.overlay_width_ratio), 920)
        h = 280
        x = max(0, (sw - w) // 2)
        y = max(40, sh - h - int(sh * cfg.overlay_margin_bottom_ratio))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self.root.after(80, self._poll_queue)

    def _toggle_topmost(self) -> None:
        self.root.attributes("-topmost", self._top_var.get())

    def _on_alpha_change(self, v: str) -> None:
        try:
            a = float(v)
        except ValueError:
            return
        self._alpha = max(0.15, min(1.0, a))
        self.root.attributes("-alpha", self._alpha)

    def _on_tw_font_change(self, v: str) -> None:
        try:
            sz = int(round(float(v)))
        except ValueError:
            return
        sz = max(12, min(40, sz))
        self._tw_font.configure(size=sz)

    def _on_en_font_change(self, v: str) -> None:
        try:
            sz = int(round(float(v)))
        except ValueError:
            return
        sz = max(9, min(26, sz))
        self._en_font.configure(size=sz)

    def _clear_text(self) -> None:
        self._tw_var.set("（已清除，等待下一句…）")
        self._en_var.set("")

    def _on_resize(self, _event: tk.Event[Any]) -> None:
        w = max(200, self._body.winfo_width() - 20)
        self._lbl_tw.configure(wraplength=w)
        self._lbl_en.configure(wraplength=w)

    def _on_press(self, e: tk.Event[Any]) -> None:
        self._offset_x = e.x_root - self.root.winfo_x()
        self._offset_y = e.y_root - self.root.winfo_y()

    def _on_motion(self, e: tk.Event[Any]) -> None:
        nx = e.x_root - self._offset_x
        ny = e.y_root - self._offset_y
        self.root.geometry(f"+{nx}+{ny}")

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._q.get_nowait()
                if msg is None:
                    self.root.after(0, self._safe_destroy)
                    return
                tw = (msg.get("tw") or "").strip()
                en = (msg.get("en") or "").strip()
                if msg.get("error"):
                    self._tw_var.set(str(msg.get("error")))
                    self._en_var.set("")
                else:
                    self._tw_var.set(tw or "（無譯文）")
                    self._en_var.set(en)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _safe_destroy(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _close(self) -> None:
        try:
            self._on_close()
        finally:
            try:
                self.root.destroy()
            except tk.TclError:
                pass

    def run(self) -> None:
        self.root.mainloop()


def run_subtitle_app(cfg: AppConfig) -> None:
    """主執行緒跑 Tk；管線在非 daemon 執行緒內跑，關閉視窗後會 join 以釋放資源。"""
    from streamgloss.pipeline import StreamGlossPipeline

    dq: queue.Queue[Optional[dict[str, str]]] = queue.Queue(maxsize=cfg.display_queue_maxsize)
    pipeline = StreamGlossPipeline(cfg, display_queue=dq)

    def shutdown() -> None:
        pipeline.stop()

    overlay = SubtitleOverlay(cfg, dq, on_close=shutdown)

    def pipeline_thread() -> None:
        try:
            pipeline.run_forever(block_on_interrupt=False)
        except Exception as e:
            try:
                dq.put_nowait({"en": "", "tw": "", "error": f"管線錯誤：{e}"})
            except queue.Full:
                pass

    t = threading.Thread(target=pipeline_thread, name="Pipeline", daemon=False)
    t.start()
    overlay.run()
    if t.is_alive():
        pipeline.stop()
        t.join(timeout=120.0)
