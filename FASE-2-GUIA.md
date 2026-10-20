# NuvemPay API v3 — Fase 2 (Cadastro)

## O que existe
| Rota | Função |
|---|---|
| `GET /`, `GET /health` | Iguais às originais (versão `3.0.0`) |
| `POST /events` | Preservada, mas com campos limitados, só campos conhecidos e 30 req/min |
| `POST /auth/register` | Cadastro (estado `pending_verification`) |
| `GET /auth/registration-status` | Estado do cadastro, só para quem tem o token daquele cadastro |

Ainda NÃO existem (próximas fases): envio/validação de código de e-mail e SMS,
login, logout, recuperação de senha, contas e transações.

## Contrato

### `POST /auth/register`
Entrada (JSON):
```json
{
  "full_name": "Maria da Silva",
  "cpf": "529.982.247-25",
  "email": "maria@exemplo.com",
  "phone": "(11) 98765-4321",
  "password": "mínimo 10 caracteres",
  "accept_terms": true,
  "terms_version": "1",
  "captcha_token": "token gerado pelo widget do Turnstile"
}
```
| HTTP | Corpo | Quando |
|---|---|---|
| 201 | `registration_id`, `registration_token`, `status`, `email_verified`, `phone_verified`, `expires_in_seconds` | Cadastro criado (pendente) |
| 400 | `{"error":"validation_error","fields":{"cpf":"invalid",...}}` | Campo inválido/ausente |
| 400 | `{"error":"captcha_failed"}` | CAPTCHA recusado ou Turnstile fora do ar |
| 409 | `{"error":"registration_conflict"}` | CPF ou e-mail já cadastrado (não diz qual) |
| 413 | `{"error":"payload_too_large"}` | Corpo > 16 KB |
| 429 | `{"error":"too_many_requests"}` | Limite: 5/hora e 20/dia por IP |
| 503 | `{"error":"service_unavailable"}` | Banco ou configuração indisponível |

O `registration_token` aparece **uma única vez**. O frontend deve guardá-lo só em
memória/`sessionStorage` durante o cadastro e usá-lo nas etapas de verificação.

### `GET /auth/registration-status?registration_id=<id>`
Cabeçalho obrigatório: `X-Registration-Token: <token>`.
200 → `status`, `email_verified`, `phone_verified`, `email_masked`, `phone_masked`.
404 para qualquer outro caso (não existe, expirou, token errado): ninguém consulta cadastro de terceiros.

## Decisões de segurança
- Senha: **Argon2id** (64 MiB, t=3). CPF: **criptografado** (Fernet) + máscara para exibição.
- Unicidade de CPF/e-mail por **índice cego** (HMAC), criado de forma atômica; falha no meio desfaz tudo.
- Cadastro pendente **expira em 24 h** (TTL do Cosmos) e libera CPF/e-mail, evitando que alguém "reserve" dados de outra pessoa.
- Conta só vira `active` quando e-mail **e** telefone forem verificados no servidor (`activate_if_complete`, já testada).
- CAPTCHA validado no servidor; **falha fechada**.
- CORS só para as origens em `ALLOWED_ORIGINS`; cabeçalhos de segurança; erros genéricos; logs sem dados pessoais; banner do servidor removido; container roda sem root.
- O hash da senha é calculado antes de checar duplicidade, para cadastros novos e duplicados demorarem o mesmo tempo.

## Limitações conhecidas (honestas)
1. **Rate limit é por réplica** (memória). No Container App, deixe **máximo de 1 réplica** por enquanto, ou use um Redis depois (`RATELIMIT_STORAGE_URI`).
2. O 409 ainda permite descobrir que *existe* um cadastro com aquele CPF/e-mail (necessário para o usuário entender o erro). A mitigação é CAPTCHA + rate limit.
3. Só celulares do **Brasil** são aceitos.
4. Os testes usam dublês (banco em memória e Turnstile falso). **Ainda não foram testados** contra o Cosmos DB real nem contra o Turnstile real: isso depende das suas chaves e dos containers abaixo.
5. `/events` continua público (rota original do projeto). Vamos protegê-lo ou removê-lo quando o frontend usar as transações autenticadas.
6. DynamoDB (AWS) só é usado por `/events`; o cadastro roda no Cosmos (Azure).

## O que você precisa configurar (uma vez)

### 1) Containers no Cosmos DB (Data Explorer → banco `nuvempay-db` → New Container)
| Container id | Partition key |
|---|---|
| `customers` | `/id` |
| `audit` | `/id` |
(`events` já existe.)

Em **cada um dos containers `customers` e `audit`**: Settings → **Time to Live → On (no default)**.
Sem isso os cadastros pendentes não expiram (a API avisa no log).

### 2) Cloudflare Turnstile (grátis)
Cloudflare → Turnstile → Add site. Você recebe a **Site key** (vai no frontend, pública) e a **Secret key** (só no servidor).

### 3) Gerar as chaves (na VM)
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"          # HMAC_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # DATA_ENCRYPTION_KEY
```
(`pip install cryptography` se faltar.) **Guarde as duas num lugar seguro: se perder a `DATA_ENCRYPTION_KEY`, os CPFs não podem mais ser lidos.**

### 4) Secrets e variáveis no Container App (portal → Container Apps → nuvempay-api)
- **Settings → Secrets**: `hmac-key`, `data-key`, `turnstile-secret` (e o `COSMOS_KEY` que já existe).
- **Containers → Edit → Environment variables** (referenciando secrets):
  `HMAC_KEY`, `DATA_ENCRYPTION_KEY`, `TURNSTILE_SECRET`, `COSMOS_URI`, `COSMOS_KEY` e
  `ALLOWED_ORIGINS` = a URL do seu site no Storage (ex.: `https://nuvempaysite.z15.web.core.windows.net`, sem barra no final).
- **Scale**: mínimo 1, **máximo 1** réplica.

> Nunca coloque essas chaves no código, no `index.html` nem no GitHub.

## Rodar os testes
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```
