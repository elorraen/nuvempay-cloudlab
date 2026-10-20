"""Validação do CAPTCHA (Cloudflare Turnstile) no servidor.

Falha fechada: qualquer erro de rede, resposta estranha ou token recusado
resulta em "não verificado". O token é de uso único no lado da Cloudflare.
"""
import requests

from .logs import log_event

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class Turnstile:
    def __init__(self, secret, hostname="", post=requests.post):
        self._secret = secret
        self._hostname = hostname
        self._post = post

    def verify(self, token, remote_ip=None) -> bool:
        if not isinstance(token, str) or not token or len(token) > 2048:
            return False
        data = {"secret": self._secret, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        try:
            response = self._post(SITEVERIFY_URL, data=data, timeout=5)
            result = response.json()
        except Exception as exc:
            log_event("Falha ao falar com o Turnstile", level=40, error=type(exc).__name__)
            return False
        if result.get("success") is not True:
            log_event("Turnstile recusou o token", codes=result.get("error-codes", []))
            return False
        if self._hostname and result.get("hostname") != self._hostname:
            log_event("Turnstile: hostname inesperado", level=30)
            return False
        return True
