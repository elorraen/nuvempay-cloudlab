import json
import time

from nuvempay import registration, security, validators
from nuvempay.app import create_app
from nuvempay.captcha import Turnstile
from nuvempay.store import MemoryStore, StoreError

from .conftest import FRONT, make_config, valid_payload


def post(client, payload, **kw):
    return client.post("/auth/register", json=payload, **kw)


# ── validadores ──────────────────────────────────────────────────────
def test_cpf_validator():
    assert validators.is_valid_cpf("529.982.247-25")
    assert validators.is_valid_cpf("52998224725")
    assert not validators.is_valid_cpf("529.982.247-24")  # dígito errado
    assert not validators.is_valid_cpf("111.111.111-11")  # repetido
    assert not validators.is_valid_cpf("123")
    assert not validators.is_valid_cpf("abc.def.ghi-jk")
    assert not validators.is_valid_cpf(None)


def test_phone_normalizes_to_e164_and_rejects_foreign_or_garbage():
    assert validators.normalize_phone_br("(11) 98765-4321") == "+5511987654321"
    assert validators.normalize_phone_br("+55 11 98765-4321") == "+5511987654321"
    assert validators.normalize_phone_br("+1 415 555 2671") is None
    assert validators.normalize_phone_br("123") is None
    assert validators.normalize_phone_br(None) is None


def test_password_policy():
    assert validators.password_error("curta") == "too_short"
    assert validators.password_error("1234567890") == "too_common"
    assert validators.password_error("aaaaaaaaaaaa") == "too_common"
    assert validators.password_error("x" * 200) == "too_long"
    assert validators.password_error("cpf52998224725ok", cpf_digits="52998224725") == "contains_cpf"
    assert validators.password_error("correct-horse-battery") is None


# ── cadastro ─────────────────────────────────────────────────────────
def test_register_success_creates_pending_customer(client, store, http):
    resp = post(client, valid_payload())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "pending_verification"
    assert body["email_verified"] is False and body["phone_verified"] is False
    assert body["registration_token"] and body["registration_id"]
    assert http.calls and http.calls[0]["response"] == "token-ok"

    customer = store.get("customers", body["registration_id"])
    assert customer["status"] == "pending_verification"
    assert customer["phone"] == "+5511987654321"
    assert customer["ttl"] == 3600


def test_response_does_not_expose_personal_data(client):
    raw = post(client, valid_payload()).get_data(as_text=True)
    for secret in ("529", "maria.silva", "98765", "password", "correct-horse"):
        assert secret not in raw


def test_password_is_argon2id_hash_and_cpf_is_encrypted(client, store, cfg):
    body = post(client, valid_payload()).get_json()
    customer = store.get("customers", body["registration_id"])
    assert customer["password_hash"].startswith("$argon2id$")
    assert "correct-horse-battery" not in json.dumps(customer)
    assert "52998224725" not in json.dumps(customer)
    assert security.decrypt_text(cfg.data_key, customer["cpf_enc"]) == "52998224725"
    assert customer["cpf_masked"] == "***.***.***-25"
    assert security.verify_password(customer["password_hash"], "correct-horse-battery")
    assert not security.verify_password(customer["password_hash"], "outra-senha-qualquer")


def test_invalid_cpf_rejected_without_calling_captcha(client, http):
    resp = post(client, valid_payload(cpf="111.111.111-11"))
    assert resp.status_code == 400
    assert resp.get_json()["fields"]["cpf"] == "invalid"
    assert http.calls == []  # token do CAPTCHA não é gasto à toa


def test_missing_required_fields(client):
    resp = post(client, {})
    assert resp.status_code == 400
    fields = resp.get_json()["fields"]
    for name in ("full_name", "cpf", "email", "phone", "password", "accept_terms", "captcha_token"):
        assert name in fields


def test_terms_must_be_accepted(client):
    resp = post(client, valid_payload(accept_terms="true"))  # string não vale
    assert resp.status_code == 400
    assert resp.get_json()["fields"]["accept_terms"] == "required"


def test_non_json_body(client):
    resp = client.post("/auth/register", data="não sou json", content_type="text/plain")
    assert resp.status_code == 400
    assert client.post("/auth/register", json=["lista"]).status_code == 400


def test_body_too_large(client):
    resp = post(client, valid_payload(full_name="A" * 20000))
    assert resp.status_code == 413


def test_invalid_captcha_rejected_and_nothing_saved(client, store):
    resp = post(client, valid_payload(captcha_token="token-falso"))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "captcha_failed"
    assert store.get("customers", security.blind_index("h" * 40, "cpf", "52998224725")) is None


def test_captcha_provider_down_fails_closed(client, http, store):
    http.down = True
    resp = post(client, valid_payload())
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "captcha_failed"


def test_duplicate_cpf_and_email_are_rejected_generically(client):
    assert post(client, valid_payload()).status_code == 201
    same_cpf = post(client, valid_payload(email="outra@example.com"))
    same_email = post(client, valid_payload(cpf="390.533.447-05"))
    for resp in (same_cpf, same_email):
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "registration_conflict"}  # não diz qual campo


def test_email_duplicate_is_case_insensitive(client):
    assert post(client, valid_payload()).status_code == 201
    resp = post(client, valid_payload(email="MARIA.SILVA@EXAMPLE.COM", cpf="390.533.447-05"))
    assert resp.status_code == 409


def test_failed_duplicate_leaves_no_orphan_index(client, store):
    assert post(client, valid_payload()).status_code == 201
    # CPF novo + e-mail repetido: o índice do CPF criado no meio deve ser desfeito
    assert post(client, valid_payload(cpf="390.533.447-05")).status_code == 409
    assert store.get("customers", security.blind_index("h" * 40, "cpf", "39053344705")) is None


def test_pending_registration_expires_and_frees_identifiers(cfg, http):
    now = [1000.0]
    store = MemoryStore(clock=lambda: now[0])
    app = create_app(cfg, store=store, captcha=Turnstile("s", post=http))
    client = app.test_client()
    assert post(client, valid_payload()).status_code == 201
    assert post(client, valid_payload()).status_code == 409
    now[0] += cfg.registration_ttl_seconds + 1  # passou o prazo
    assert post(client, valid_payload()).status_code == 201


def test_database_failure_returns_503_without_details(cfg, http):
    class BrokenStore(MemoryStore):
        def create(self, container, doc):
            if container == "customers":
                raise StoreError("CosmosHttpResponseError")
            super().create(container, doc)

    app = create_app(cfg, store=BrokenStore(), captcha=Turnstile("s", post=http))
    resp = post(app.test_client(), valid_payload())
    assert resp.status_code == 503
    assert resp.get_json() == {"error": "service_unavailable"}


def test_register_unavailable_when_secrets_missing(store, http):
    cfg = make_config(turnstile_secret="")
    app = create_app(cfg, store=store, captcha=Turnstile("", post=http))
    assert post(app.test_client(), valid_payload()).status_code == 503


def test_register_is_rate_limited(client):
    codes = [post(client, valid_payload(cpf="111.111.111-11")).status_code for _ in range(6)]
    assert codes[:5] == [400] * 5
    assert codes[5] == 429


# ── status do cadastro ───────────────────────────────────────────────
def test_status_requires_the_registration_token(client):
    body = post(client, valid_payload()).get_json()
    url = f"/auth/registration-status?registration_id={body['registration_id']}"

    ok = client.get(url, headers={"X-Registration-Token": body["registration_token"]})
    assert ok.status_code == 200
    data = ok.get_json()
    assert data["status"] == "pending_verification"
    assert data["email_masked"] == "m***@example.com"
    assert data["phone_masked"].endswith("4321") and "98765" not in data["phone_masked"]

    assert client.get(url).status_code == 404
    assert client.get(url, headers={"X-Registration-Token": "errado"}).status_code == 404
    assert client.get("/auth/registration-status", headers={"X-Registration-Token": "x"}).status_code == 404


def test_status_does_not_leak_other_customers(client):
    first = post(client, valid_payload()).get_json()
    second = post(client, valid_payload(
        cpf="390.533.447-05", email="joao@example.com", phone="(21) 99876-5432")).get_json()
    url = f"/auth/registration-status?registration_id={first['registration_id']}"
    # token do cadastro 2 não abre o cadastro 1
    resp = client.get(url, headers={"X-Registration-Token": second["registration_token"]})
    assert resp.status_code == 404


def test_activation_only_after_both_verifications(client, store):
    body = post(client, valid_payload()).get_json()
    customer = store.get("customers", body["registration_id"])

    customer["email_verified"] = True
    assert registration.activate_if_complete(store, customer)["status"] == "pending_verification"

    customer["phone_verified"] = True
    activated = registration.activate_if_complete(store, customer)
    assert activated["status"] == "active"
    assert store.get("customers", body["registration_id"])["ttl"] == -1
    assert store.get("customers", customer["index_keys"][0])["ttl"] == -1  # deixa de expirar


# ── CORS, cabeçalhos e rotas legadas ─────────────────────────────────
def test_cors_only_for_allowed_origin(client):
    ok = client.get("/health", headers={"Origin": FRONT})
    assert ok.headers["Access-Control-Allow-Origin"] == FRONT
    assert ok.headers["Access-Control-Allow-Credentials"] == "true"
    bad = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in bad.headers


def test_preflight(client):
    resp = client.options("/auth/register", headers={
        "Origin": FRONT, "Access-Control-Request-Method": "POST"})
    assert resp.status_code in (200, 204)
    assert resp.headers["Access-Control-Allow-Origin"] == FRONT


def test_security_headers_and_no_store_on_auth(client):
    resp = client.get("/auth/registration-status")
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "Strict-Transport-Security" in resp.headers


def test_legacy_routes_preserved(client, store):
    assert client.get("/").get_json() == {"name": "nuvempay", "version": "3.0.0"}
    health = client.get("/health").get_json()
    assert health["status"] == "ok" and "timestamp" in health
    resp = client.post("/events", json={"type": "transaction.created", "source": "nuvempay",
                                        "amount": 150.0, "message": "x" * 900, "extra": "ignorado"})
    assert resp.status_code == 201 and resp.get_json()["status"] == "received"
    saved = store.get("events", resp.get_json()["id"])
    assert len(saved["message"]) == 500 and "extra" not in saved


def test_unknown_route_and_method_return_generic_json(client):
    assert client.get("/nao-existe").get_json() == {"error": "not_found"}
    assert client.delete("/health").status_code == 405
