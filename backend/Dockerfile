FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# onnxruntime (OCR) needs libgomp; PyMuPDF/Pillow ship their own wheels.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-ocr.txt backend/requirements.txt.d/
RUN pip install --no-cache-dir -r backend/requirements.txt.d/requirements-ocr.txt reportlab==4.2.5

COPY backend backend
COPY scripts scripts
# Regenerate the synthetic dataset (dates are relative to build/run day) so the image is self-contained.
RUN python scripts/generate_sample_data.py --out /srv/sample_data

ENV SAMPLE_DIR=/srv/sample_data DATABASE_URL=sqlite:////data/invoiceiq.db UPLOAD_DIR=/data/uploads
VOLUME /data
EXPOSE 8000
WORKDIR /srv/backend
# Schema is created/migrated on start (alembic upgrade head), master data is seeded on first boot.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
