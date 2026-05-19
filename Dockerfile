FROM python:3.12-slim

WORKDIR /app

# Dependencias del sistema (algunas libs nativas necesitan compilarse)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar requirements primero (mejor caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código
COPY app/ ./app/

# Puerto (Railway inyecta $PORT)
ENV PORT=8000
EXPOSE 8000

# Comando de arranque
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
