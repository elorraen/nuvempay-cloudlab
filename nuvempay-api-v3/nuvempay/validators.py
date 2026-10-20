"""Validação de entrada feita SEMPRE no servidor."""
import re

import phonenumbers
from email_validator import EmailNotValidError, validate_email

COMMON_PASSWORDS = {
    "1234567890", "12345678910", "senha12345", "password123", "qwertyuiop",
    "1q2w3e4r5t", "senhasenha", "nuvempay123", "abcdefghij", "0123456789",
}


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def is_valid_cpf(raw: str) -> bool:
    if not isinstance(raw, str) or not re.fullmatch(r"[\d.\-\s]{11,14}", raw):
        return False
    cpf = only_digits(raw)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for n in (9, 10):
        total = sum(int(cpf[i]) * (n + 1 - i) for i in range(n))
        if (total * 10) % 11 % 10 != int(cpf[n]):
            return False
    return True


def normalize_email(raw: str):
    """Retorna o e-mail normalizado em minúsculas ou None se inválido.
    A sintaxe válida NÃO prova que a caixa existe: isso é feito pelo código."""
    if not isinstance(raw, str) or len(raw) > 254:
        return None
    try:
        result = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError:
        return None
    return result.normalized.lower()


def normalize_phone_br(raw: str):
    """Normaliza para E.164. Por ora só aceita celulares do Brasil."""
    if not isinstance(raw, str) or len(raw) > 30:
        return None
    try:
        number = phonenumbers.parse(raw, "BR")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    if phonenumbers.region_code_for_number(number) != "BR":
        return None
    if phonenumbers.number_type(number) not in (
        phonenumbers.PhoneNumberType.MOBILE,
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
    ):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_name(raw: str):
    if not isinstance(raw, str):
        return None
    name = re.sub(r"\s+", " ", raw).strip()
    if not (3 <= len(name) <= 120) or len(name.split(" ")) < 2:
        return None
    if any(ord(ch) < 32 for ch in name) or re.search(r"[<>{}\[\]\\/@#$%^*=+|~`]", name):
        return None
    return name


def password_error(password, cpf_digits="", email=""):
    """Política baseada em tamanho (NIST 800-63B). Retorna código do erro ou None."""
    if not isinstance(password, str):
        return "invalid"
    if len(password) < 10:
        return "too_short"
    if len(password) > 128:
        return "too_long"
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(lowered)) < 4:
        return "too_common"
    if cpf_digits and cpf_digits in only_digits(password):
        return "contains_cpf"
    local = email.split("@")[0] if email else ""
    if len(local) >= 4 and local in lowered:
        return "contains_email"
    return None


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_phone(e164: str) -> str:
    return "*" * max(len(e164) - 4, 0) + e164[-4:]


def validate_registration(body: dict):
    """Valida o corpo de /auth/register. Retorna (dados_limpos, erros)."""
    errors = {}
    cleaned = {}

    name = normalize_name(body.get("full_name"))
    if not name:
        errors["full_name"] = "invalid"
    cleaned["full_name"] = name

    cpf_raw = body.get("cpf")
    if not is_valid_cpf(cpf_raw):
        errors["cpf"] = "invalid"
        cleaned["cpf"] = None
    else:
        cleaned["cpf"] = only_digits(cpf_raw)

    email = normalize_email(body.get("email"))
    if not email:
        errors["email"] = "invalid"
    cleaned["email"] = email

    phone = normalize_phone_br(body.get("phone"))
    if not phone:
        errors["phone"] = "invalid"
    cleaned["phone"] = phone

    pwd_err = password_error(body.get("password"), cleaned["cpf"] or "", email or "")
    if pwd_err:
        errors["password"] = pwd_err
    cleaned["password"] = body.get("password") if not pwd_err else None

    if body.get("accept_terms") is not True:
        errors["accept_terms"] = "required"
    terms_version = body.get("terms_version", "1")
    cleaned["terms_version"] = terms_version if isinstance(terms_version, str) and len(terms_version) <= 20 else "1"

    token = body.get("captcha_token")
    if not isinstance(token, str) or not token or len(token) > 2048:
        errors["captcha_token"] = "required"
    cleaned["captcha_token"] = token

    return cleaned, errors
