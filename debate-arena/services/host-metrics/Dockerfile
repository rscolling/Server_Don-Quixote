FROM python:3.12-slim
WORKDIR /app

# psutil reads from /proc — set the path to the host /proc that we'll mount.
ENV PROCFS_PATH=/host/proc

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Run as non-root. host /proc and / are mounted READ-ONLY anyway, but defense in depth.
RUN useradd -r -u 1000 -m metrics && chown -R metrics:metrics /app
USER metrics

EXPOSE 8111
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8111"]
