FROM python:3.11-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs /app/data \
    && chown -R appuser:appuser /app/logs /app/data

EXPOSE 19377

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD python -c "import httpx; r = httpx.get('http://localhost:19377/health', timeout=5.0); assert r.status_code == 200" || exit 1

CMD ["python", "main.py"]
