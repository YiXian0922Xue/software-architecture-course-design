import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """Return a consistently formatted application logger.

    Uvicorn owns its own logging configuration, so LabScribe uses a dedicated
    logger instead of relying on the root logger being configured first.
    """
    base = logging.getLogger("labscribe")
    if not base.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        ))
        base.addHandler(handler)
        base.setLevel(logging.INFO)
        base.propagate = False
    return logging.getLogger(f"labscribe.{name}")
