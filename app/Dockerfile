# Imagem base leve — reduz tamanho final e superfície de exposição
FROM python:3.12-slim

WORKDIR /app

# Copia só o requirements primeiro (aproveita cache de camadas do Docker
# quando o código mudar mas as dependências não)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8080

CMD ["python", "app.py"]
