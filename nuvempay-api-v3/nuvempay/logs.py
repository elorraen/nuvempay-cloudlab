"""Logs estruturados em JSON no stdout (coletados pelo Azure Monitor/CloudWatch).

Regra: NUNCA passar senha, CPF, código de verificação, token ou e-mail/telefone
completos para estas funções.
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # werkzeug imprime cada requisição com a URL completa; silenciamos.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


logger = logging.getLogger("nuvempay")


def log_event(message, level=logging.INFO, **fields):
    logger.log(level, message, extra={"fields": fields})
