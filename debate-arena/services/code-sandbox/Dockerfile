FROM python:3.12-slim
WORKDIR /app

# Install ruff (Python lint) at the OS-package level via pip — small footprint.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Run as non-root for defense in depth (sandbox reads code; never trust it).
RUN useradd -r -u 1000 -m sandbox && chown -R sandbox:sandbox /app
USER sandbox

EXPOSE 8110
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8110"]
