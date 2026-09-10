"""Logging configuration.

structlog is the primary interface. stdlib loggers (uvicorn, libraries) are
routed through the same renderer via ``ProcessorFormatter`` so every line shares
one format: JSON when ``json_logs`` is true, a colored console renderer locally.
Per-request context (the correlation id) is merged in through
``structlog.contextvars``.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog


def configure_logging(*, json_logs: bool, level: str) -> None:
    """Install the structlog + stdlib logging pipeline. Idempotent."""

    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        timestamper,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    renderer: Any = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
