bind = "0.0.0.0:8080"
workers = 2
threads = 4
timeout = 30
graceful_timeout = 20
limit_request_line = 4094
limit_request_fields = 50
accesslog = None  # evita registrar URLs com parâmetros; os eventos úteis vão pelo audit
errorlog = "-"

# Esconde o banner "Server: gunicorn/versão" (menos informação para quem faz reconhecimento)
import gunicorn

gunicorn.SERVER = "nuvempay"
