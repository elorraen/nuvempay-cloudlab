"""Rota legada POST /events (contrato original do projeto).

Preservada para não quebrar o frontend atual, mas endurecida: tamanho dos
campos limitado, só campos conhecidos são gravados e limite de requisições.
"""
import uuid
from datetime import datetime, timezone

from .logs import log_event


def clean_event(body: dict):
    def text(key, limit):
        value = body.get(key, "")
        return value[:limit] if isinstance(value, str) else ""

    amount = body.get("amount", "")
    if isinstance(amount, bool) or not isinstance(amount, (int, float, str)):
        amount = ""
    return {
        "type": text("type", 64),
        "source": text("source", 64),
        "amount": str(amount)[:32],
        "message": text("message", 500),
    }


class EventsSink:
    """Grava eventos no Cosmos (Azure) ou DynamoDB (AWS), conforme configuração."""

    def __init__(self, cfg, store=None):
        self.backend = "none"
        self._store = None
        self._table = None
        if store is not None:
            self._store, self.backend = store, "store"
        elif cfg.aws_region and not cfg.cosmos_uri:
            try:
                import boto3

                self._table = boto3.resource("dynamodb", region_name=cfg.aws_region).Table(cfg.dynamo_table)
                self.backend = "dynamodb"
            except Exception as exc:
                log_event("Falha ao iniciar DynamoDB", level=40, error=type(exc).__name__)

    def save(self, body: dict) -> str:
        event_id = str(uuid.uuid4())
        item = {
            "id": event_id,
            **clean_event(body),
            "status": "received",
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        if self._store is not None:
            self._store.create("events", item)
        elif self._table is not None:
            self._table.put_item(Item=item)
        else:
            raise RuntimeError("nenhum backend configurado")
        return event_id
