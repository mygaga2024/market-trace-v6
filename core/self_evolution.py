"""
Market Trace V6.0 — 项目自我进化模块 v2

这是 project-evolve skill 的项目本地副本。
新增: 梦境蒸馏、进化日志、备份快照、开关控制。

通用脚本路径: ~/.config/opencode/skills/project-evolve/evolution.py
数据存储: .project_evolution.yaml + .evolution/
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

EVOLUTION_FILE = Path(__file__).parent.parent / ".project_evolution.yaml"

_DEFAULT: dict[str, Any] = {
    "version": 2,
    "created": "",
    "updated": "",
    "self_evolution_enabled": True,
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
                if isinstance(data, dict):
                    merged = {**_DEFAULT, **data}
                    if "version" not in data or data.get("version", 1) < 2:
                        merged["version"] = 2
                    return merged
        except Exception:
            pass
    return {**_DEFAULT}


def _save(data: dict[str, Any]) -> None:
    data["updated"] = datetime.now().isoformat()
    EVOLUTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EVOLUTION_FILE, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _is_enabled() -> bool:
    return _load().get("self_evolution_enabled", True)


def _evo_dir() -> Path:
    return EVOLUTION_FILE.parent / ".evolution"


def _append_md(filepath: Path, title: str, content: str) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H:%M")
    with open(filepath, "a") as f:
        f.write(f"\n## {title} ({ts})\n\n{content}\n")


# ── Core API ──

def add_fix(error: str, fix: str, files: list[str], session: str = "") -> None:
    if not _is_enabled(): return
    data = _load()
    data["fixes"].append({"error": error, "fix": fix, "files": files,
                          "session": session, "timestamp": datetime.now().isoformat()})
    _save(data)


def add_anti_pattern(name: str, description: str, session: str = "") -> None:
    if not _is_enabled(): return
    data = _load()
    data["anti_patterns"].append({"name": name, "description": description,
                                   "session": session, "timestamp": datetime.now().isoformat()})
    _save(data)


def add_style_pattern(category: str, description: str, files: list[str], session: str = "") -> None:
    if not _is_enabled(): return
    data = _load()
    data["style"].append({"category": category, "description": description, "files": files,
                           "session": session, "timestamp": datetime.now().isoformat()})
    _save(data)


def add_architecture(decision: str, rationale: str, session: str = "") -> None:
    if not _is_enabled(): return
    data = _load()
    data["architecture"].append({"decision": decision, "rationale": rationale,
                                  "session": session, "timestamp": datetime.now().isoformat()})
    _save(data)


# ── v2 新功能 ──

def backup() -> str | None:
    if not _is_enabled() or not EVOLUTION_FILE.exists():
        return None
    dst = _evo_dir() / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EVOLUTION_FILE, dst / "evolution.yaml")
    return dst.name


def record_dream(summary: str, session: str = "") -> None:
    if not _is_enabled(): return
    f = _evo_dir() / "dreams" / f"{datetime.now():%Y-%m-%d}.md"
    _append_md(f, f"Dream ({session})" if session else "Dream", summary)


def record_evolution(summary: str, session: str = "") -> None:
    if not _is_enabled(): return
    f = _evo_dir() / "logs" / f"{datetime.now():%Y-%m-%d}.md"
    _append_md(f, f"Evolution ({session})" if session else "Evolution", summary)


def toggle_enabled(state: bool) -> None:
    data = _load()
    data["self_evolution_enabled"] = state
    _save(data)


def get_dreams(limit: int = 7) -> str:
    d = _evo_dir() / "dreams"
    if not d.exists(): return "No dreams yet."
    files = sorted(d.glob("*.md"), reverse=True)[:limit]
    return "\n\n---\n\n".join(f.read_text().strip() for f in files) if files else "No dreams yet."


def get_evolution_logs(limit: int = 7) -> str:
    d = _evo_dir() / "logs"
    if not d.exists(): return "No evolution logs yet."
    files = sorted(d.glob("*.md"), reverse=True)[:limit]
    return "\n\n---\n\n".join(f.read_text().strip() for f in files) if files else "No evolution logs yet."


# ── Context ──

def get_evolution_context() -> str:
    data = _load()
    parts: list[str] = []

    if not data.get("self_evolution_enabled", True):
        parts.append("⚠️ Self-evolution is DISABLED.")

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

    dreams = get_dreams(3)
    if dreams and "No dreams" not in dreams:
        parts.append("## 近期梦境蒸馏")
        parts.append(dreams)

    logs = get_evolution_logs(3)
    if logs and "No evolution" not in logs:
        parts.append("## 近期进化日志")
        parts.append(logs)

    return "\n\n".join(parts) if parts else "无进化数据。项目尚未积累跨会话知识。"


def get_stats() -> dict[str, int]:
    data = _load()
    return {
        "fixes": len(data.get("fixes", [])),
        "anti_patterns": len(data.get("anti_patterns", [])),
        "style": len(data.get("style", [])),
        "architecture": len(data.get("architecture", [])),
    }


def init_if_needed() -> bool:
    if EVOLUTION_FILE.exists():
        return False
    data = {**_DEFAULT, "created": datetime.now().isoformat()}
    _save(data)
    return True


if __name__ == "__main__":
    import sys
    if "--init" in sys.argv:
        if init_if_needed():
            print(f"已创建 {EVOLUTION_FILE}")
        else:
            print(f"{EVOLUTION_FILE} 已存在")
    context = get_evolution_context()
    stats = get_stats()
    print(f"=== 项目进化状态 v2 ({EVOLUTION_FILE}) ===")
    print(f"修复: {stats['fixes']} | 反模式: {stats['anti_patterns']} | 风格: {stats['style']} | 架构: {stats['architecture']}")
    print()
    print(context)
