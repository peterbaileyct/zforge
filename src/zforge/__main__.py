"""Z-Forge entry point."""

import logging

import flet as ft

from zforge.app import main as app_main


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Reduce chatter from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("llama_cpp").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.INFO)
    logging.getLogger("langchain").setLevel(logging.INFO)


def main() -> None:
    _configure_logging()
    ft.app(target=app_main)


if __name__ == "__main__":
    main()
