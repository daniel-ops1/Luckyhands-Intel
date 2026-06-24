FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY config.py tools.py agents.py render.py send.py run.py template.html ./
COPY adk_agents/ ./adk_agents/

RUN mkdir -p /app/output

ENV OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    LLM_BACKEND=ollama \
    OLLAMA_RESEARCHER_MODEL=qwen-intel \
    OLLAMA_EDITOR_MODEL=qwen-intel \
    PYTHONPATH=/app

EXPOSE 8000

CMD ["adk", "web", "adk_agents", "--host", "0.0.0.0", "--port", "8000"]
