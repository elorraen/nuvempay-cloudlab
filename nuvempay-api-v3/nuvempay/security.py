"""Primitivas de segurança: hash de senha, índices cegos, criptografia, tokens."""
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type
from cryptography.fernet import Fernet, InvalidToken

# Argon2id (recomendação OWASP: >= 19 MiB de memória, t=2). Usamos 64 MiB, t=3.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, type=Type.ID)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def blind_index(hmac_key: str, namespace: str, value: str) -> str:
    """HMAC-SHA256 determinístico: permite buscar/garantir unicidade de e-mail e
    CPF sem guardar esses valores como chave em texto puro."""
    digest = hmac.new(hmac_key.encode(), f"{namespace}:{value}".encode(), hashlib.sha256)
    return f"{namespace}:{digest.hexdigest()}"


def encrypt_text(data_key: str, plaintext: str) -> str:
    return Fernet(data_key.encode()).encrypt(plaintext.encode()).decode()


def decrypt_text(data_key: str, token: str):
    try:
        return Fernet(data_key.encode()).decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def new_token() -> str:
    """Token imprevisível (256 bits) para uso único/curto."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    # Tokens têm 256 bits de entropia, então SHA-256 simples é suficiente.
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(token_hash(token), expected_hash or "")
