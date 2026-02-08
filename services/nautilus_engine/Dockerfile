FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG INSTALL_NAUTILUS_TRADER=0

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt \
    && if [ "$INSTALL_NAUTILUS_TRADER" = "1" ]; then pip install nautilus-trader; else echo "nautilus-trader optional install skipped (set INSTALL_NAUTILUS_TRADER=1)"; fi

COPY nautilus_engine /app/nautilus_engine

CMD ["python", "-m", "nautilus_engine.main"]
