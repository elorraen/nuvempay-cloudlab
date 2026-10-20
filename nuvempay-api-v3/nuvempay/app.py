"""NuvemPay API v3 — fábrica da aplicação Flask.

Rotas:
  GET  /                           identificação do serviço (legado)
  GET  /health                     saúde (legado)
  POST /events                     evento sintético (legado, endurecido)
  POST /auth/register              cadastro de cliente (Fase 2)
  GET  /auth/registration-status   estado do cadastro, só com o token do próprio cadastro
"""
import hmac

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from . import audit, registration, security, validators
from .captcha import Turnstile
from .config import Config
from .legacy_events import EventsSink
from .logs import log_event, setup_logging
from .store import CosmosStore, MemoryStore, StoreError

SERVICE_NAME = "nuvempay"
SERVICE_VERSION = "3.0.0"


def _error(status, code, **extra):
    body = {"error": code}
    body.update(extra)
    return jsonify(body), status


def create_app(config=None, store=None, captcha=None):
    setup_logging()
    cfg = config or Config.from_env()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # corpo máximo de 16 KB
    app.config["JSON_SORT_KEYS"] = False
    # O ingress do Container Apps adiciona 1 salto em X-Forwarded-For.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ── persistência ────────────────────────────────────────────────
    if store is None and cfg.cosmos_uri and cfg.cosmos_key:
        try:
            store = CosmosStore(cfg.cosmos_uri, cfg.cosmos_key, cfg.cosmos_database)
            store.check_ttl_enabled("customers")
            log_event("Backend de persistência ativo: Azure Cosmos DB")
        except Exception as exc:
            log_event("Falha ao iniciar o Cosmos DB", level=40, error=type(exc).__name__)
            store = None
    if store is None and not cfg.aws_region:
        log_event("Nenhum banco configurado: cadastro indisponível", level=30)

    events_sink = EventsSink(cfg, store=store)
    turnstile = captcha or Turnstile(cfg.turnstile_secret, cfg.turnstile_hostname)

    # ── rate limit ──────────────────────────────────────────────────
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["120 per minute"],
        storage_uri=cfg.ratelimit_storage,
    )
    limiter.request_filter(lambda: request.method == "OPTIONS")

    # ── CORS restrito + cabeçalhos de segurança ─────────────────────
    @app.after_request
    def secure_headers(response):
        origin = request.headers.get("Origin")
        if origin and origin in cfg.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Registration-Token, X-CSRF-Token"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "600"
        response.headers.add("Vary", "Origin")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.path.startswith("/auth/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ── erros genéricos (sem detalhes internos) ─────────────────────
    @app.errorhandler(404)
    def not_found(_):
        return _error(404, "not_found")

    @app.errorhandler(405)
    def method_not_allowed(_):
        return _error(405, "method_not_allowed")

    @app.errorhandler(413)
    def too_large(_):
        return _error(413, "payload_too_large")

    @app.errorhandler(429)
    def rate_limited(_):
        return _error(429, "too_many_requests")

    @app.errorhandler(Exception)
    def unexpected(exc):
        log_event("Erro inesperado", level=40, error=type(exc).__name__, path=request.path)
        return _error(500, "internal_error")

    # ── rotas legadas ───────────────────────────────────────────────
    @app.get("/")
    def root():
        return jsonify({"name": SERVICE_NAME, "version": SERVICE_VERSION}), 200

    @app.get("/health")
    def health():
        from datetime import datetime, timezone

        return jsonify({
            "status": "ok",
            "version": SERVICE_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    @app.post("/events")
    @limiter.limit("30 per minute")
    def events():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            body = {}
        try:
            event_id = events_sink.save(body)
        except Exception as exc:
            # Como no contrato original, a persistência não trava a resposta.
            log_event("Falha ao gravar evento", level=40, error=type(exc).__name__)
            import uuid
            event_id = str(uuid.uuid4())
        return jsonify({"id": event_id, "status": "received"}), 201

    # ── cadastro ────────────────────────────────────────────────────
    @app.post("/auth/register")
    @limiter.limit("5 per hour")
    @limiter.limit("20 per day")
    def register():
        ip = request.remote_addr

        missing = cfg.missing_for_registration()
        if missing or store is None:
            log_event("Cadastro indisponível por configuração", level=40, missing=[m.split(" ")[0] for m in missing],
                      has_store=store is not None)
            return _error(503, "service_unavailable")

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _error(400, "invalid_json")

        data, errors = validators.validate_registration(body)
        if errors:
            return _error(400, "validation_error", fields=errors)

        if not turnstile.verify(data["captcha_token"], ip):
            audit.record(store, "auth.register", "captcha_failed", ip=ip)
            return _error(400, "captcha_failed")

        # O hash é calculado ANTES de checar duplicidade para que cadastros
        # novos e duplicados levem o mesmo tempo (evita oráculo de tempo).
        password_hash = security.hash_password(data["password"])

        try:
            customer, token = registration.create_pending_customer(store, cfg, data, password_hash)
        except registration.DuplicateError:
            audit.record(store, "auth.register", "duplicate", ip=ip)
            # Mensagem genérica: não revela qual dado já existe.
            return _error(409, "registration_conflict")
        except StoreError:
            log_event("Falha de banco no cadastro", level=40)
            return _error(503, "service_unavailable")

        audit.record(store, "auth.register", "created", customer_id=customer["id"], ip=ip)
        return jsonify({
            "registration_id": customer["id"],
            "registration_token": token,
            "status": customer["status"],
            "email_verified": False,
            "phone_verified": False,
            "expires_in_seconds": cfg.registration_ttl_seconds,
        }), 201

    @app.get("/auth/registration-status")
    @limiter.limit("30 per minute")
    def registration_status():
        reg_id = request.args.get("registration_id", "")
        token = request.headers.get("X-Registration-Token", "")
        if store is None or not reg_id or not token or len(reg_id) > 64 or len(token) > 128:
            return _error(404, "not_found")
        try:
            customer = store.get(registration.CUSTOMERS, reg_id)
        except StoreError:
            return _error(503, "service_unavailable")

        # Mesma resposta para "não existe", "expirou" e "token errado":
        # ninguém consegue consultar o cadastro de terceiros.
        if (
            not customer
            or customer.get("type") != "customer"
            or not security.tokens_match(token, customer.get("registration_token_hash", ""))
        ):
            return _error(404, "not_found")

        return jsonify({
            "status": customer["status"],
            "email_verified": customer["email_verified"],
            "phone_verified": customer["phone_verified"],
            "email_masked": validators.mask_email(customer["email"]),
            "phone_masked": validators.mask_phone(customer["phone"]),
        }), 200

    return app
