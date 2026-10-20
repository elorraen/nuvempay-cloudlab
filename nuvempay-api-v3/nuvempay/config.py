"""Configuração lida SOMENTE de variáveis de ambiente.

Nenhum segredo fica no código nem no repositório. Em produção os valores
vêm dos secrets do Azure Container Apps (ou, depois, do Key Vault).
"""
import os
from dataclasses import dataclass, field


def _csv(value):
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Config:
    # Origens (sites) autorizadas a chamar a API pelo navegador.
    # Vazio = nenhuma origem recebe cabeçalhos CORS (falha fechada).
    allowed_origins: list = field(default_factory=list)

    # Banco de dados (Cosmos DB na Azure)
    cosmos_uri: str = ""
    cosmos_key: str = ""
    cosmos_database: str = "nuvempay-db"

    # Rota legada /events na AWS (DynamoDB)
    aws_region: str = ""
    dynamo_table: str = "nuvempay-events"

    # Segredos de proteção de dados
    hmac_key: str = ""   # "pimenta" para índices de busca (e-mail/CPF); >= 32 caracteres
    data_key: str = ""   # chave Fernet para criptografar o CPF (Fernet.generate_key())

    # CAPTCHA (Cloudflare Turnstile)
    turnstile_secret: str = ""
    turnstile_hostname: str = ""  # opcional: hostname esperado do site

    # Cadastro pendente expira (e libera e-mail/CPF) após este prazo
    registration_ttl_seconds: int = 86400

    # Rate limit: em produção com mais de 1 réplica use um storage compartilhado
    ratelimit_storage: str = "memory://"

    @classmethod
    def from_env(cls):
        env = os.environ
        return cls(
            allowed_origins=_csv(env.get("ALLOWED_ORIGINS", "")),
            cosmos_uri=env.get("COSMOS_URI", ""),
            cosmos_key=env.get("COSMOS_KEY", ""),
            cosmos_database=env.get("COSMOS_DATABASE", "nuvempay-db"),
            aws_region=env.get("AWS_REGION", ""),
            dynamo_table=env.get("DYNAMO_TABLE_NAME", "nuvempay-events"),
            hmac_key=env.get("HMAC_KEY", ""),
            data_key=env.get("DATA_ENCRYPTION_KEY", ""),
            turnstile_secret=env.get("TURNSTILE_SECRET", ""),
            turnstile_hostname=env.get("TURNSTILE_HOSTNAME", ""),
            registration_ttl_seconds=int(env.get("REGISTRATION_TTL_SECONDS", "86400")),
            ratelimit_storage=env.get("RATELIMIT_STORAGE_URI", "memory://"),
        )

    def missing_for_registration(self):
        """Nomes das configurações obrigatórias que estão faltando."""
        missing = []
        if len(self.hmac_key) < 32:
            missing.append("HMAC_KEY (mínimo 32 caracteres)")
        if not self.data_key:
            missing.append("DATA_ENCRYPTION_KEY")
        if not self.turnstile_secret:
            missing.append("TURNSTILE_SECRET")
        return missing
