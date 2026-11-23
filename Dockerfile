# Single-container build for Render / Railway / Fly: React UI + FastAPI API on one port.
# Stage 1: build the frontend (VITE_API_URL is intentionally unset -> same-origin calls, no CORS needed)
FROM node:22-alpine AS ui
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build

# Stage 2: API + OCR + built UI
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# onnxruntime (OCR) needs libgomp
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-ocr.txt backend/req/
RUN pip install --no-cache-dir -r backend/req/requirements-ocr.txt reportlab==4.2.5

COPY backend backend
COPY scripts scripts
# Synthetic dataset (dates relative to build day) so the image is self-contained
RUN python scripts/generate_sample_data.py --out /srv/sample_data
# config.py serves /srv/frontend/dist automatically when it exists
COPY --from=ui /app/dist /srv/frontend/dist

ENV SAMPLE_DIR=/srv/sample_data DATABASE_URL=sqlite:////data/invoiceiq.db UPLOAD_DIR=/data/uploads
RUN mkdir -p /data/uploads
VOLUME /data
WORKDIR /srv/backend
# Render injects $PORT; default 8000 elsewhere
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
