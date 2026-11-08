"""Структурированное логирование: одна JSON-строка на событие в stdout.

Метрики шага передаются через `extra`, например
`log.info("loaded", extra={"step": "core_prices", "rows": 1000})`,
и попадают в JSON отдельными полями, а не текстом сообщения.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

# Стандартные атрибуты LogRecord: всё остальное в record.__dict__ пришло из extra.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
