"""Auditoria de eventos de segurança e de negócio.

Grava no container "audit" e também no log. Nunca recebe senha, código,
token, CPF ou contato completo. Falha de auditoria não derruba a requisição,
mas é registrada no log.
"""
import uuid
from datetime import datetime, timezone

from .logs import log_event

AUDIT_CONTAINER = "audit"
AUDIT_TTL_SECONDS = 365 * 24 * 3600  # retenção de 1 ano: ajustar conforme política da empresa/LGPD


def record(store, event, outcome, customer_id=None, ip=None, **meta):
    doc = {
        "id": str(uuid.uuid4()),
        "event": event,
        "outcome": outcome,
        "customer_id": customer_id,
        "ip": ip,
        "at": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
        "ttl": AUDIT_TTL_SECONDS,
    }
    log_event("audit", audit_event=event, outcome=outcome, customer_id=customer_id, ip=ip, **meta)
    try:
        store.create(AUDIT_CONTAINER, doc)
    except Exception as exc:
        log_event("Falha ao gravar auditoria", level=40, error=type(exc).__name__)
