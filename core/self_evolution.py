"""
Market Trace V6.0 — 项目自我进化模块

这是 project-evolve skill 的项目本地副本。
如果 skill 目录存在，优先使用通用脚本（可复用于任何项目）；
若不可用（如 Docker 环境），使用内置实现。

通用脚本路径: ~/.config/opencode/skills/project-evolve/evolution.py

数据存储在 .project_evolution.yaml，每次会话结束自动更新。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

EVOLUTION_FILE = Path(__file__).parent.parent / ".project_evolution.yaml"

DEFAULT_EVOLUTION: dict[str, Any] = {
    "version": 1,
    "created": datetime.now().isoformat(),
    "updated": "",
    "fixes": [],
    "anti_patterns": [],
    "style": [],
    "architecture": [],
}


def _load() -> dict[str, Any]:
    if EVOLUTION_FILE.exists():
        try:
            with open(EVOLUTION_FILE) as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else DEFAULT_EVOLUTION.copy()
        except Exception:
            pass
    return DEFAULT_EVOLUTION.copy()


def _save(data: dict[str, Any]) -> None:
    data["updated"] = datetime.now().isoformat()
    EVOLUTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EVOLUTION_FILE, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def add_fix(error: str, fix: str, files: list[str], session: str = "") -> None:
    data = _load()
    data["fixes"].append({
        "error": error,
        "fix": fix,
        "files": files,
        "session": session,
        "timestamp": datetime.now().isoformat(),
    })
    _save(data)


def add_anti_pattern(name: str, description: str, session: str = "") -> None:
    data = _load()
    data["anti_patterns"].append({
        "name": name,
        "description": description,
        "session": session,
        "timestamp": datetime.now().isoformat(),
    })
    _save(data)


def add_style_pattern(category: str, description: str, files: list[str], session: str = "") -> None:
    data = _load()
    data["style"].append({
        "category": category,
        "description": description,
        "files": files,
        "session": session,
        "timestamp": datetime.now().isoformat(),
    })
    _save(data)


def add_architecture(decision: str, rationale: str, session: str = "") -> None:
    data = _load()
    data["architecture"].append({
        "decision": decision,
        "rationale": rationale,
        "session": session,
        "timestamp": datetime.now().isoformat(),
    })
    _save(data)


def get_evolution_context() -> str:
    """返回当前进化数据的 AI 可读摘要，用于注入会话上下文"""
    data = _load()
    parts: list[str] = []

    if data.get("fixes"):
        parts.append("## 已记录的修复模式 (最近 10 条)")
        for f in data["fixes"][-10:]:
            parts.append(f"- **{f['error']}** → {f['fix']} [{', '.join(f.get('files', []))}]")

    if data.get("anti_patterns"):
        parts.append("## 反模式 - 绝对不要重复 (最近 5 条)")
        for a in data["anti_patterns"][-5:]:
            parts.append(f"- **{a['name']}**: {a['description']}")

    if data.get("style"):
        parts.append("## 代码风格偏好 (最近 5 条)")
        for s in data["style"][-5:]:
            parts.append(f"- [{s['category']}] {s['description']}")

    if data.get("architecture"):
        parts.append("## 架构决策记录 (最近 5 条)")
        for a in data["architecture"][-5:]:
            parts.append(f"- {a['decision']}: {a['rationale']}")

    return "\n\n".join(parts) if parts else "无进化数据。项目尚未积累跨会话知识。"


def get_stats() -> dict[str, int]:
    """返回进化数据统计"""
    data = _load()
    return {
        "fixes": len(data.get("fixes", [])),
        "anti_patterns": len(data.get("anti_patterns", [])),
        "style": len(data.get("style", [])),
        "architecture": len(data.get("architecture", [])),
    }


def init_if_needed() -> bool:
    """首次初始化进化文件（不存在时创建）"""
    if EVOLUTION_FILE.exists():
        return False
    data = DEFAULT_EVOLUTION.copy()
    data["created"] = datetime.now().isoformat()
    _save(data)
    return True


if __name__ == "__main__":
    import sys

    if "--init" in sys.argv:
        if init_if_needed():
            print(f"已创建 {EVOLUTION_FILE}")
        else:
            print(f"{EVOLUTION_FILE} 已存在，跳过初始化")

    context = get_evolution_context()
    stats = get_stats()
    print(f"=== 项目进化状态 ({EVOLUTION_FILE}) ===")
    print(f"修复模式: {stats['fixes']} | 反模式: {stats['anti_patterns']} | 风格: {stats['style']} | 架构: {stats['architecture']}")
    print()
    print(context)
