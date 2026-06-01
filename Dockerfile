FROM python:3.11-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN groupadd -r -g 1000 appuser && useradd -r -u 1000 -g appuser appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs /app/data \
    && chown -R appuser:appuser /app/logs /app/data

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 19377

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -sf http://localhost:19377/health || exit 1

CMD ["python", "main.py"]
