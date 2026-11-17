FROM python:3.12-slim

WORKDIR /app

COPY requirements/ ./requirements/
RUN pip install --no-cache-dir -r requirements/serve.txt

COPY src/ ./src/
COPY configs/ ./configs/
COPY db/ ./db/

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=postgresql://agro:agro@timescaledb:5432/agro \
    REDIS_URL=redis://redis:6379/0 \
    CROP_CONFIG_DIR=/app/configs/crops

EXPOSE 8000

CMD ["uvicorn", "agro_growth.api:app", "--host", "0.0.0.0", "--port", "8000"]
