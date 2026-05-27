"""
Market Trace V6.0 — 启动入口
初始化消息总线，启动 FastAPI，为后续 Agent 启动预留接口
"""

import os
import sys
import time
from pathlib import Path

import yaml
import uvicorn
from dotenv import load_dotenv
from loguru import logger

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# --- 环境变量加载 ---
load_dotenv()

# --- 配置加载 ---
CONFIG_PATH = Path("config/settings.yaml")

def _resolve_env_vars(raw: str) -> str:
    """替换 ${VAR} 为环境变量值"""
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)
    return raw

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        logger.error("配置文件不存在: {}", CONFIG_PATH.absolute())
        sys.exit(1)
    raw = CONFIG_PATH.read_text(encoding="utf-8")
    raw = _resolve_env_vars(raw)
    return yaml.safe_load(raw)

CONFIG = load_config()

# --- Loguru 日志配置 ---
logger.remove()
log_cfg = CONFIG["logging"]

logger.add(
    Path("logs") / "market_trace_{time:YYYY-MM-DD}.log",
    rotation=log_cfg["rotation"],
    retention=log_cfg["retention"],
    level=log_cfg["level"],
    format=log_cfg["format"],
    encoding="utf-8",
    enqueue=True,
)
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    colorize=True,
)

# --- 全局状态 ---
START_TIME = time.time()
bus = None

# --- FastAPI 生命周期 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global bus
    from core.bus import MessageBus

    redis_cfg = CONFIG["redis"]
    bus = MessageBus(
        host=redis_cfg["host"],
        port=redis_cfg["port"],
        db=redis_cfg["db"],
        password=redis_cfg["password"],
        max_connections=redis_cfg["max_connections"],
        retry_interval=redis_cfg["retry_interval"],
    )
    await bus.connect()
    logger.info("系统启动完成，Redis 已连接")

    yield

    if bus:
        await bus.close()
    logger.info("系统已关闭")

app = FastAPI(
    title="Market Trace V6.0",
    description="A/B 股量化分析系统 — 多 Agent 协作 + AI 决策",
    version="0.1.0",
    lifespan=lifespan,
)

# --- API 路由 ---

@app.get("/health")
async def health():
    """系统健康检查"""
    redis_ok = False
    if bus:
        try:
            redis_ok = await bus.health_check()
        except Exception:
            pass

    agents = {}
    if bus and redis_ok:
        try:
            agents = await bus.check_all_heartbeats(["macro", "signal", "trace", "risk", "chief"])
        except Exception:
            pass

    uptime = time.time() - START_TIME

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected",
        "version": "0.1.0",
        "uptime_seconds": round(uptime, 1),
        "agents": agents,
        "active_llm": f"primary:{CONFIG['llm']['primary']['provider']}({CONFIG['llm']['primary']['model']})",
    }

@app.get("/status")
async def status():
    """系统状态概览"""
    return {
        "version": "0.1.0",
        "phase": 1,
        "agents_implemented": [],
        "available_endpoints": ["/health", "/status"],
    }

# --- 入口 ---

def main():
    logger.info("Market Trace V6.0 正在启动...")
    logger.info("LLM 主力: {}::{}", CONFIG["llm"]["primary"]["provider"], CONFIG["llm"]["primary"]["model"])
    logger.info("数据源: {}", [p["name"] for p in CONFIG["data_providers"] if p.get("enabled")])

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,
        access_log=False,
    )

if __name__ == "__main__":
    main()
