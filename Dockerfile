FROM python:3.11-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 系统依赖（最少变更的层 → 放最前面以利用缓存）
RUN apt-get update && apt-get install -y --no-install-recommends curl tzdata \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r -g 1000 appuser && useradd -r -u 1000 -g appuser appuser

WORKDIR /app

# Python 依赖（仅 requirements.txt 变更时重建此层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 源代码（最频繁变更的层 → 放最后）
COPY . .

RUN mkdir -p /app/logs /app/data \
    && chown -R appuser:appuser /app/logs /app/data

EXPOSE 19377

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -sf http://localhost:19377/health || exit 1

CMD ["python", "main.py"]
