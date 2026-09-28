FROM python:3.12-slim

# Evita que o Python gere arquivos .pyc e força saída não-bufferizada para logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências do sistema para compilação e suporte a banco e imagens
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python (incluindo daphne e channels para ASGI)
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação (respeitando .dockerignore)
COPY . /app/

# Cria diretórios necessários para mídia e arquivos estáticos
RUN mkdir -p /app/media /app/staticfiles

# Porta padrão de execução interna
EXPOSE 8000

# Execução padrão em produção via Daphne (ASGI / WebSockets)
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
