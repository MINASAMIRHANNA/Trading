FROM node:20-alpine AS ui
WORKDIR /ui
COPY services/brain/dashboard/package.json services/brain/dashboard/package-lock.json* ./
RUN npm ci
COPY services/brain/dashboard/ ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY gateway/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

COPY gateway /app
COPY --from=ui /ui/dist /app/ui_dist

EXPOSE 8200

CMD ["uvicorn", "gateway_api.main:app", "--host", "0.0.0.0", "--port", "8200"]
