import pytest

from nuvempay.app import create_app
from nuvempay.captcha import Turnstile
from nuvempay.config import Config
from nuvempay.store import MemoryStore

FRONT = "https://nuvempaysite.z15.web.core.windows.net"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeTurnstileHttp:
    """Dublê do serviço da Cloudflare: aceita só o token 'token-ok'."""

    def __init__(self):
        self.calls = []
        self.down = False

    def __call__(self, url, data=None, timeout=None):
        self.calls.append(data)
        if self.down:
            raise ConnectionError("fora do ar")
        return FakeResponse({"success": data["response"] == "token-ok", "hostname": "site"})


def make_config(**overrides):
    base = dict(
        allowed_origins=[FRONT],
        hmac_key="h" * 40,
        data_key="3Ij8W9S3cJ9r0v6n3o3o0o3o3o3o3o3o3o3o3o3o3o0=",
        turnstile_secret="segredo-de-teste",
        registration_ttl_seconds=3600,
    )
    base.update(overrides)
    return Config(**base)


@pytest.fixture
def http():
    return FakeTurnstileHttp()


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def cfg():
    from cryptography.fernet import Fernet

    return make_config(data_key=Fernet.generate_key().decode())


@pytest.fixture
def app(cfg, store, http):
    application = create_app(cfg, store=store, captcha=Turnstile(cfg.turnstile_secret, post=http))
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def valid_payload(**overrides):
    payload = {
        "full_name": "Maria da Silva",
        "cpf": "529.982.247-25",
        "email": "maria.silva@example.com",
        "phone": "(11) 98765-4321",
        "password": "correct-horse-battery",
        "accept_terms": True,
        "captcha_token": "token-ok",
    }
    payload.update(overrides)
    return payload
