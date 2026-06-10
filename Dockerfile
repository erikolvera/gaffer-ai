# Container build — works on Railway, Fly.io, Cloud Run, or any Docker host.
#   docker build -t gaffer-ai .
#   docker run -p 8000:8000 -e GEMINI_API_KEY=... gaffer-ai
FROM python:3.12-slim

WORKDIR /app

# Dependencies first: this layer caches as long as requirements.txt is unchanged.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY briefing_engine/ briefing_engine/

EXPOSE 8000

# $PORT is injected by most platforms; default to 8000 for local docker run.
CMD ["sh", "-c", "uvicorn briefing_engine.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
