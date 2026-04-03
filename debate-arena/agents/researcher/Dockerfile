FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
CMD ["sh", "-c", "cp -r /common /tmp/common && pip install --no-cache-dir /tmp/common && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8100}"]
