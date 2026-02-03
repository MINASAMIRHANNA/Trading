FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (xgboost wheels rely on libgomp; others for clean installs)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       curl \
       libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

COPY . /app

EXPOSE 8000 8001 8002

# Default (overridden by docker-compose commands)
CMD ["python", "main.py"]
