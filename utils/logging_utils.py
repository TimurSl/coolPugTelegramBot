"""Logging configuration helpers."""

from __future__ import annotations

import json
import logging
import logging.config
from datetime import datetime
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """Serialize log records into JSON for easier ingestion."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - trivial
        base = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            base["stack_info"] = record.stack_info
        return json.dumps(base, ensure_ascii=False)


def configure_logging(log_dir: Path, *, level: str = "INFO") -> None:
    """Configure the logging subsystem with structured and human-readable outputs."""

    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    text_log_path = log_dir / f"{timestamp}.log"
    json_log_path = log_dir / f"{timestamp}.jsonl"
    latest_log_path = log_dir / "latest.log"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "console": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                },
                "detailed": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(processName)s(%(process)d) | %(threadName)s(%(thread)d) | %(message)s",
                },
                "json": {
                    "()": JsonFormatter,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "console",
                    "level": level,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "detailed",
                    "filename": str(text_log_path),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "level": "DEBUG",
                },
                "latest": {
                    "class": "logging.FileHandler",
                    "formatter": "detailed",
                    "filename": str(latest_log_path),
                    "mode": "w",
                    "encoding": "utf-8",
                    "level": "DEBUG",
                },
                "json": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "json",
                    "filename": str(json_log_path),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 3,
                    "encoding": "utf-8",
                    "level": "INFO",
                },
            },
            "root": {
                "handlers": ["console", "file", "latest", "json"],
                "level": "DEBUG",
            },
        }
    )

    logging.getLogger(__name__).debug(
        "Logging configured: text=%s latest=%s json=%s",
        text_log_path,
        latest_log_path,
        json_log_path,
    )

