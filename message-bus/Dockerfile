FROM python:3.12-slim

RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -m appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /app/data && chown appuser:appuser /app/data

USER appuser

EXPOSE 8585

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8585"]
