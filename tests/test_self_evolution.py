"""
Market Trace V6.0 — 自我进化模块测试
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import core.self_evolution as evo


@pytest.fixture
def temp_evolution_file():
    """创建临时进化文件进行测试"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("version: 1\nfixes: []\nanti_patterns: []\nstyle: []\narchitecture: []\n")
        tmp_path = Path(f.name)

    org_path = evo.EVOLUTION_FILE
    evo.EVOLUTION_FILE = tmp_path
    yield tmp_path
    evo.EVOLUTION_FILE = org_path
    tmp_path.unlink(missing_ok=True)


class TestSelfEvolution:
    def test_init_if_needed_creates_file(self, tmp_path):
        """首次初始化应该创建文件"""
        test_file = tmp_path / ".project_evolution.yaml"
        with patch.object(evo, "EVOLUTION_FILE", test_file):
            assert evo.init_if_needed() is True
            assert test_file.exists()

    def test_init_if_needed_skips_existing(self, tmp_path):
        """文件已存在时跳过初始化"""
        test_file = tmp_path / ".project_evolution.yaml"
        test_file.write_text("version: 1\n")
        with patch.object(evo, "EVOLUTION_FILE", test_file):
            assert evo.init_if_needed() is False

    def test_add_fix(self, temp_evolution_file):
        evo.add_fix("test error", "test fix", ["file.py"], "session-1")
        data = evo._load()
        assert len(data["fixes"]) == 1
        assert data["fixes"][0]["error"] == "test error"
        assert data["fixes"][0]["fix"] == "test fix"
        assert data["fixes"][0]["session"] == "session-1"

    def test_add_fix_preserves_existing(self, temp_evolution_file):
        evo.add_fix("error A", "fix A", ["a.py"], "s1")
        evo.add_fix("error B", "fix B", ["b.py"], "s2")
        data = evo._load()
        assert len(data["fixes"]) == 2

    def test_add_anti_pattern(self, temp_evolution_file):
        evo.add_anti_pattern("Bad Pattern", "Don't do this", "session-1")
        data = evo._load()
        assert len(data["anti_patterns"]) == 1
        assert data["anti_patterns"][0]["name"] == "Bad Pattern"

    def test_add_style_pattern(self, temp_evolution_file):
        evo.add_style_pattern("imports", "Use annotations", ["file.py"], "session-1")
        data = evo._load()
        assert len(data["style"]) == 1
        assert data["style"][0]["category"] == "imports"

    def test_add_architecture(self, temp_evolution_file):
        evo.add_architecture("Split modules", "Reduce coupling", "session-1")
        data = evo._load()
        assert len(data["architecture"]) == 1
        assert data["architecture"][0]["decision"] == "Split modules"

    def test_get_evolution_context_empty(self, temp_evolution_file):
        context = evo.get_evolution_context()
        assert "无进化数据" in context

    def test_get_evolution_context_with_data(self, temp_evolution_file):
        evo.add_fix("error X", "fix X", ["x.py"], "s1")
        evo.add_anti_pattern("Bad", "Avoid", "s1")
        evo.add_style_pattern("fmt", "Use black", ["y.py"], "s1")
        evo.add_architecture("Decision A", "Because", "s1")
        context = evo.get_evolution_context()
        assert "修复模式" in context
        assert "error X" in context
        assert "反模式" in context
        assert "Bad" in context
        assert "风格" in context
        assert "fmt" in context
        assert "架构" in context
        assert "Decision A" in context

    def test_get_stats(self, temp_evolution_file):
        assert evo.get_stats() == {"fixes": 0, "anti_patterns": 0, "style": 0, "architecture": 0}
        evo.add_fix("e", "f", ["f.py"])
        evo.add_anti_pattern("a", "d")
        evo.add_style_pattern("s", "d", ["s.py"])
        assert evo.get_stats() == {"fixes": 1, "anti_patterns": 1, "style": 1, "architecture": 0}

    def test_context_only_shows_recent_entries(self, temp_evolution_file):
        """修复模式只显示最近 10 条，反模式/风格/架构只显示最近 5 条"""
        for i in range(15):
            evo.add_fix(f"error {i}", f"fix {i}", ["f.py"], f"s{i}")
            evo.add_anti_pattern(f"bad {i}", f"avoid {i}", f"s{i}")
            evo.add_style_pattern(f"cat {i}", f"desc {i}", ["f.py"], f"s{i}")
            evo.add_architecture(f"dec {i}", f"rationale {i}", f"s{i}")

        context = evo.get_evolution_context()
        assert "error 14" in context
        assert "error 4" not in context

        lines = context.split("\n")
        anti_lines = [l for l in lines if "bad" in l]
        assert len(anti_lines) <= 5

    def test_load_corrupted_file(self, tmp_path):
        """损坏的 YAML 文件应回退到默认"""
        test_file = tmp_path / "corrupt.yaml"
        test_file.write_text(": invalid yaml :::")
        with patch.object(evo, "EVOLUTION_FILE", test_file):
            data = evo._load()
            assert data["fixes"] == []

    def test_module_import(self):
        """确保模块可正确导入"""
        import core.self_evolution
        assert hasattr(core.self_evolution, "add_fix")
        assert hasattr(core.self_evolution, "get_evolution_context")
        assert hasattr(core.self_evolution, "get_stats")
