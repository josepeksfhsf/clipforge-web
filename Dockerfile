FROM node:24-bookworm-slim AS js_runtime
FROM python:3.12-slim
COPY --from=js_runtime /usr/local/bin/node /usr/local/bin/node
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates libatomic1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN node --version
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Cache the small CPU speech-recognition model in the image so jobs don't download it.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8', cpu_threads=1, download_root='/app/models')"
COPY main.py smart_engine.py ./
COPY static ./static
ENV PORT=10000
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
