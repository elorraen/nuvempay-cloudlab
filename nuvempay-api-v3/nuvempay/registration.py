"""Regras de negócio do cadastro (independentes do Flask)."""
import uuid
from datetime import datetime, timezone

from . import security
from .store import ConflictError

CUSTOMERS = "customers"

STATUS_PENDING = "pending_verification"
STATUS_ACTIVE = "active"
STATUS_BLOCKED = "blocked"


class DuplicateError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def create_pending_customer(store, cfg, data, password_hash):
    """Cria cliente em estado pending_verification.

    Unicidade de e-mail e CPF: documentos-índice com id = HMAC do valor. O
    create_item do banco é atômico, então duas requisições simultâneas com o
    mesmo CPF/e-mail não passam as duas. Se algo falhar no meio, desfazemos.
    Retorna (customer_doc, registration_token).
    """
    email_key = security.blind_index(cfg.hmac_key, "email", data["email"])
    cpf_key = security.blind_index(cfg.hmac_key, "cpf", data["cpf"])
    customer_id = str(uuid.uuid4())
    ttl = cfg.registration_ttl_seconds
    created = []

    try:
        for key in (email_key, cpf_key):
            try:
                store.create(CUSTOMERS, {"id": key, "type": "index", "customer_id": customer_id, "ttl": ttl})
            except ConflictError as exc:
                raise DuplicateError() from exc
            created.append(key)

        token = security.new_token()
        customer = {
            "id": customer_id,
            "type": "customer",
            "full_name": data["full_name"],
            "cpf_enc": security.encrypt_text(cfg.data_key, data["cpf"]),
            "cpf_masked": f"***.***.***-{data['cpf'][-2:]}",
            "email": data["email"],
            "email_verified": False,
            "phone": data["phone"],
            "phone_verified": False,
            "password_hash": password_hash,
            "status": STATUS_PENDING,
            "terms": {"version": data["terms_version"], "accepted_at": _now()},
            "registration_token_hash": security.token_hash(token),
            "index_keys": [email_key, cpf_key],
            "created_at": _now(),
            "updated_at": _now(),
            "ttl": ttl,
        }
        store.create(CUSTOMERS, customer)
        return customer, token
    except Exception:
        for key in created:
            try:
                store.delete(CUSTOMERS, key)
            except Exception:
                pass
        raise


def activate_if_complete(store, customer):
    """Ativa a conta somente se e-mail E telefone foram verificados no servidor.
    Remove o TTL do cliente e dos índices (o cadastro deixa de expirar)."""
    if customer["status"] != STATUS_PENDING:
        return customer
    if not (customer["email_verified"] and customer["phone_verified"]):
        return customer
    customer["status"] = STATUS_ACTIVE
    customer["updated_at"] = _now()
    customer["ttl"] = -1
    store.replace(CUSTOMERS, customer)
    for key in customer["index_keys"]:
        store.replace(CUSTOMERS, {"id": key, "type": "index", "customer_id": customer["id"], "ttl": -1})
    return customer
