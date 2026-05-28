"""
Market Trace V6.0 — 微信告警推送

支持: WxPusher (免费, 个人微信)
配置: env 中设置 WXPUSHER_TOKEN (https://wxpusher.zjiecode.com)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

_WXPUSHER_API = "https://wxpusher.zjiecode.com/api/send/message"


class Notifier:
    """微信推送通知器"""

    def __init__(self, token: str = "", uid: str = ""):
        self._token = token
        self._uid = uid
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def enabled(self) -> bool:
        return bool(self._token) and bool(self._uid)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self._client

    async def send(self, title: str, content: str, content_type: int = 1) -> bool:
        """
        发送微信通知

        Args:
            title: 通知标题
            content: 通知内容 (content_type=1 时支持 Markdown)
            content_type: 1=文字, 2=HTML, 3=Markdown
        """
        if not self.enabled:
            return False

        try:
            client = await self._get_client()
            resp = await client.post(_WXPUSHER_API, json={
                "appToken": self._token,
                "content": content,
                "summary": title,
                "contentType": content_type,
                "uids": [self._uid],
            })
            data = resp.json()
            if data.get("code") == 1000:
                logger.debug("微信通知发送成功: {}", title)
                return True
            else:
                logger.warning("微信通知失败: {}", data.get("msg", "unknown"))
                return False
        except Exception as e:
            logger.warning("微信通知异常: {}", e)
            return False

    async def alert_decision(self, symbol: str, action: str, confidence: float,
                              price: float, reason: str = "") -> bool:
        """交易决策告警"""
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "WAIT": "⏳"}.get(action, "📊")
        msg = (
            f"## {emoji} {action} {symbol}\n\n"
            f"> 价格: **{price:.2f}** | 置信度: **{confidence:.0%}**\n\n"
            f"> {reason}\n\n"
            f"---\n{datetime.now().strftime('%m-%d %H:%M')}"
        )
        return await self.send(f"{action} {symbol} 决策提醒", msg, 3)

    async def alert_risk(self, reason: str, severity: str = "warning") -> bool:
        """风控告警"""
        emoji = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📢")
        msg = (
            f"## {emoji} 风控[{severity.upper()}]\n\n"
            f"> {reason}\n\n"
            f"---\n{datetime.now().strftime('%m-%d %H:%M')}"
        )
        return await self.send(f"风控 {severity}", msg, 3)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


_notifier_instance: Optional[Notifier] = None


def get_notifier() -> Notifier:
    global _notifier_instance
    if _notifier_instance is None:
        import os
        token = os.environ.get("WXPUSHER_TOKEN", "")
        uid = os.environ.get("WXPUSHER_UID", "")
        _notifier_instance = Notifier(token=token, uid=uid)
    return _notifier_instance
