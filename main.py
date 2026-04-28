"""
StreamGloss entrypoint: modular producer-consumer live translation.
"""

from __future__ import annotations

import logging
import sys

from streamgloss.config import AppConfig
from streamgloss.pipeline import StreamGlossPipeline


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
    )
    for noisy in ("faster_whisper", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        import torch

        torch.set_num_threads(1)
    except ImportError:
        pass

    cfg = AppConfig(
        input_device_index=3,
    )
    argv = [a for a in sys.argv[1:] if a != "--no-gui"]
    if "--no-gui" in sys.argv:
        cfg.use_subtitle_overlay = False
    if argv:
        try:
            cfg.input_device_index = int(argv[0])
        except ValueError:
            print("Usage: python main.py [input_device_index] [--no-gui]")
            sys.exit(1)

    if cfg.use_subtitle_overlay:
        from streamgloss.subtitle_overlay import run_subtitle_app

        run_subtitle_app(cfg)
    else:
        StreamGlossPipeline(cfg).run_forever()


if __name__ == "__main__":
    main()
