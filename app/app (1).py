import logging
import sys
import uuid
from datetime import datetime, timezone

import boto3
from flask import Flask, jsonify, request

def add_cors_headers(response):
    # Libera chamadas vindas do navegador (ex: o painel NuvemPay em HTML/JS)
    # para esta API. Como é um projeto acadêmico de demonstração, liberamos
    # qualquer origem ("*") — em um cenário real, isso seria restrito ao
    # domínio específico do frontend.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# Logs estruturados na saída padrão (stdout) — é isso que o CloudWatch
# vai coletar automaticamente quando o container rodar no ECS/Fargate.
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}'
)
logger = logging.getLogger("nuvempay")

app = Flask(__name__)
app.after_request(add_cors_headers)

SERVICE_NAME = "nuvempay"
SERVICE_VERSION = "1.0.0"

# Cliente do DynamoDB. A região deve bater com a região onde a tabela
# foi criada (us-east-1, no ambiente do Learner Lab).
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
events_table = dynamodb.Table("nuvempay-events")


@app.route("/", methods=["GET"])
def root():
    logger.info("Requisição recebida em GET /")
    return jsonify({
        "name": SERVICE_NAME,
        "version": SERVICE_VERSION
    }), 200


@app.route("/health", methods=["GET"])
def health():
    logger.info("Requisição recebida em GET /health")
    return jsonify({
        "status": "ok",
        "version": SERVICE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route("/events", methods=["POST"])
def events():
    body = request.get_json(silent=True) or {}
    event_id = str(uuid.uuid4())

    # Aqui é só registrar o evento recebido (log estruturado).
    # Não há validação de saldo, cálculo de taxa ou regra de negócio —
    # o campo "amount" é tratado só como dado do JSON, sem lógica financeira.
    logger.info(
        f'Evento recebido id={event_id} type={body.get("type")} '
        f'source={body.get("source")} amount={body.get("amount")}'
    )

    # Persiste o evento no DynamoDB. Se essa gravação falhar (ex: problema
    # de permissão IAM), registramos o erro no log mas ainda respondemos
    # ao cliente — persistência é um complemento, não deve travar a API.
    try:
        events_table.put_item(Item={
            "id": event_id,
            "type": body.get("type", ""),
            "source": body.get("source", ""),
            "amount": str(body.get("amount", "")),
            "message": body.get("message", ""),
            "status": "received",
            "received_at": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        logger.info(f"Falha ao gravar no DynamoDB: {str(e)}")

    return jsonify({
        "id": event_id,
        "status": "received"
    }), 201


if __name__ == "__main__":
    # host 0.0.0.0 é necessário para o container aceitar conexões
    # de fora dele (não só de dentro do próprio container).
    app.run(host="0.0.0.0", port=8080)
