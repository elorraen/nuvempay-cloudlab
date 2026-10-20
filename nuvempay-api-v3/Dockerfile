# Imagem base leve — reduz tamanho final e superfície de exposição
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copia só o requirements primeiro (cache de camadas do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gunicorn.conf.py .
COPY nuvempay ./nuvempay

# Roda sem privilégios de root
RUN useradd --system --no-create-home appuser
USER appuser

EXPOSE 8080

CMD ["gunicorn", "-c", "gunicorn.conf.py", "nuvempay.app:create_app()"]
