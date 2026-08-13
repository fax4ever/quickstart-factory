"""Tests for pipeline-checkpoint.py."""

import importlib
import logging
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Run every test inside a fresh temp directory."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    """Import pipeline-checkpoint as a module, redirecting LOG_DIR to tmp."""
    log_dir = tmp_path / ".tmp"
    log_dir.mkdir()

    mod_name = "pipeline_checkpoint"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    monkeypatch.setattr("pathlib.Path.mkdir", lambda *a, **kw: None)

    import importlib.util
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_DIR / "pipeline-checkpoint.py")
    m = importlib.util.module_from_spec(spec)

    import logging as _logging
    m.logging = _logging
    m.Path = Path
    m.LOG_DIR = log_dir
    _logging.basicConfig(filename=str(log_dir / "test.log"), level=_logging.DEBUG, force=True)

    monkeypatch.undo()
    monkeypatch.chdir(tmp_path)

    spec.loader.exec_module(m)
    m.LOG_DIR = log_dir
    return m


SAMPLE_SKILLS = [
    {
        "id": "skill-1",
        "order": 1,
        "description": "First step",
        "expected_inputs": [
            {"name": "qs-name", "description": "Quickstart slug"},
        ],
        "expected_outputs": [{"path": ".rhoai-qs/{qs-name}/flow/output-1.md"}],
        "review_guidance": "Check output-1.",
    },
    {
        "id": "skill-2",
        "order": 2,
        "description": "Second step",
        "expected_inputs": [
            {"name": "qs-name", "description": "Quickstart slug"},
        ],
        "expected_outputs": [{"path": ".rhoai-qs/{qs-name}/flow/output-2.md"}],
        "review_guidance": "Check output-2.",
    },
    {
        "id": "skill-3",
        "order": 3,
        "description": "Third step",
        "expected_inputs": [
            {"name": "qs-name", "description": "Quickstart slug"},
            {"name": "file-name", "description": "File name to create"},
        ],
        "expected_outputs": [{"path": ".rhoai-qs/{qs-name}/flow/output-3.md"}],
        "review_guidance": "",
    },
]


# ── parse_dashboard_frontmatter ──────────────────────────────────────────


class TestParseDashboardFrontmatter:
    def test_valid_frontmatter(self, mod):
        text = "---\nqs_name: demo\n---\n# Body"
        assert mod.parse_dashboard_frontmatter(text) == {"qs_name": "demo"}

    def test_no_frontmatter(self, mod):
        assert mod.parse_dashboard_frontmatter("# No frontmatter") == {}

    def test_empty_frontmatter(self, mod):
        assert mod.parse_dashboard_frontmatter("---\n---\n# Body") == {}


# ── serialise_frontmatter ────────────────────────────────────────────────


class TestSerialiseFrontmatter:
    def test_roundtrip(self, mod):
        data = {"qs_name": "demo", "created_at": "2026-01-01"}
        text = mod.serialise_frontmatter(data)
        assert text.startswith("---\n")
        assert text.endswith("\n---")
        parsed = yaml.safe_load(text.strip("- \n"))
        assert parsed["qs_name"] == "demo"


# ── validate_outputs ─────────────────────────────────────────────────────


class TestValidateOutputs:
    def test_no_expected_outputs(self, mod):
        assert mod.validate_outputs({"id": "x"}, "demo") is True

    def test_missing_file(self, mod):
        skill = {"id": "x", "expected_outputs": [{"path": "nonexistent.md"}]}
        assert mod.validate_outputs(skill, "demo") is False

    def test_fresh_file_passes(self, mod, tmp_path):
        out = tmp_path / "out.md"
        out.write_text("ok")
        skill = {"id": "x", "expected_outputs": [{"path": str(out)}]}
        assert mod.validate_outputs(skill, "demo") is True

    def test_stale_file_fails(self, mod, tmp_path):
        out = tmp_path / "out.md"
        out.write_text("ok")
        stale_time = time.time() - mod.FRESHNESS_WINDOW - 10
        os.utime(out, (stale_time, stale_time))
        skill = {"id": "x", "expected_outputs": [{"path": str(out)}]}
        assert mod.validate_outputs(skill, "demo") is False

    def test_qs_name_substitution(self, mod, tmp_path):
        out_dir = tmp_path / ".rhoai-qs" / "demo" / "flow"
        out_dir.mkdir(parents=True)
        out_file = out_dir / "output-1.md"
        out_file.write_text("content")
        pattern = str(tmp_path / ".rhoai-qs/{qs-name}/flow/output-1.md")
        skill = {"id": "x", "expected_outputs": [{"path": pattern}]}
        assert mod.validate_outputs(skill, "demo") is True

    def test_string_output_spec(self, mod, tmp_path):
        out = tmp_path / "plain.md"
        out.write_text("ok")
        skill = {"id": "x", "expected_outputs": [str(out)]}
        assert mod.validate_outputs(skill, "demo") is True

    def test_glob_pattern(self, mod, tmp_path):
        d = tmp_path / "outputs"
        d.mkdir()
        (d / "a.md").write_text("ok")
        (d / "b.md").write_text("ok")
        skill = {"id": "x", "expected_outputs": [{"path": str(d / "*.md")}]}
        assert mod.validate_outputs(skill, "demo") is True
        
    def test_glob_pattern_without_match(self, mod, tmp_path):
        d = tmp_path / "outputs"
        d.mkdir()
        skill = {"id": "x", "expected_outputs": [{"path": str(d / "*.md")}]}
        assert mod.validate_outputs(skill, "demo") is False


# ── render_dashboard ─────────────────────────────────────────────────────


class TestRenderDashboard:
    def test_all_pending(self, mod):
        md = mod.render_dashboard("demo", SAMPLE_SKILLS, {})
        assert "demo" in md
        assert "0% (0/3 steps)" in md
        assert "⏳" in md
        assert "Next Step" in md
        assert "skill-1" in md
        assert "Pipeline Complete" not in md


    def test_one_done(self, mod):
        state = {"skill-1": {"status": "done", "completed_at": "2026-01-01T00:00:00", "outputs_verified": True}}
        md = mod.render_dashboard("demo", SAMPLE_SKILLS, state)
        assert "33% (1/3 steps)" in md
        assert "✅" in md
        assert "Review Before Continuing" in md
        assert "Next Step" in md
        assert "skill-2" in md
        assert "Pipeline Complete" not in md


    def test_all_done(self, mod):
        state = {
            f"skill-{i}": {"status": "done", "completed_at": "2026-01-01", "outputs_verified": True}
            for i in range(1, 4)
        }
        md = mod.render_dashboard("demo", SAMPLE_SKILLS, state)
        assert "100% (3/3 steps)" in md
        assert "Pipeline Complete" in md
        assert "Next Step" not in md

    def test_unverified_output_shows_warning(self, mod):
        state = {"skill-1": {"status": "done", "completed_at": "2026-01-01", "outputs_verified": False}}
        md = mod.render_dashboard("demo", SAMPLE_SKILLS, state)
        assert "⚠️" in md
        assert "Output not found" in md

    def test_output_link_uses_qs_name(self, mod):
        state = {"skill-1": {"status": "done", "completed_at": "2026-01-01", "outputs_verified": True}}
        md = mod.render_dashboard("demo", SAMPLE_SKILLS, state)
        assert "output-1.md" in md
        assert "{qs-name}" not in md

    def test_frontmatter_is_valid_yaml(self, mod):
        md = mod.render_dashboard("demo", SAMPLE_SKILLS, {})
        fm = mod.parse_dashboard_frontmatter(md)
        assert fm["qs_name"] == "demo"
        assert "skills" in fm

    def test_next_step_qs_name_input_resolved(self, mod):
        md = mod.render_dashboard("demo", SAMPLE_SKILLS, {})
        assert "/skill-1 qs-name=demo" in md

    def test_next_step_multiple_inputs_with_placeholder(self, mod):
        """skill-3 has both qs-name and file-name; file-name should render as placeholder."""
        state = {
            "skill-1": {"status": "done", "completed_at": "2026-01-01", "outputs_verified": True},
            "skill-2": {"status": "done", "completed_at": "2026-01-01", "outputs_verified": True},
        }
        md = mod.render_dashboard("demo", SAMPLE_SKILLS, state)
        assert "/skill-3 qs-name=demo file-name=<file-name>" in md

    def test_progress_bar_partial(self, mod):
        state = {"skill-1": {"status": "done"}, "skill-2": {"status": "done"}}
        md = mod.render_dashboard("demo", SAMPLE_SKILLS, state)
        assert "█" in md
        assert "░" in md
        assert "67%" in md


# ── update_dashboard ─────────────────────────────────────────────────────


class TestUpdateDashboard:
    def test_creates_dashboard_from_scratch(self, mod):
        path = mod.update_dashboard("demo", "skill-1", SAMPLE_SKILLS, True)
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "demo" in content
        assert "✅" in content

    def test_idempotent_update(self, mod):
        mod.update_dashboard("demo", "skill-1", SAMPLE_SKILLS, True)
        path = mod.update_dashboard("demo", "skill-1", SAMPLE_SKILLS, True)
        content = Path(path).read_text()
        fm = mod.parse_dashboard_frontmatter(content)
        assert fm["skills"]["skill-1"]["status"] == "done"

    def test_sequential_skills(self, mod):
        mod.update_dashboard("demo", "skill-1", SAMPLE_SKILLS, True)
        path = mod.update_dashboard("demo", "skill-2", SAMPLE_SKILLS, True)
        content = Path(path).read_text()
        fm = mod.parse_dashboard_frontmatter(content)
        assert fm["skills"]["skill-1"]["status"] == "done"
        assert fm["skills"]["skill-2"]["status"] == "done"
        assert fm["skills"]["skill-3"]["status"] == "pending"

    def test_preserves_created_at(self, mod):
        mod.update_dashboard("demo", "skill-1", SAMPLE_SKILLS, True)
        path = Path(mod.update_dashboard("demo", "skill-1", SAMPLE_SKILLS, True))
        fm1 = mod.parse_dashboard_frontmatter(path.read_text())

        mod.update_dashboard("demo", "skill-2", SAMPLE_SKILLS, True)
        fm2 = mod.parse_dashboard_frontmatter(path.read_text())
        assert fm1.get("created_at") == fm2.get("created_at")

    def test_dashboard_directory_structure(self, mod, tmp_path):
        mod.update_dashboard("demo", "skill-1", SAMPLE_SKILLS, True)
        assert (tmp_path / ".rhoai-qs" / "demo" / "flow" / "dashboard.md").exists()
        assert (tmp_path / ".tmp" / "demo" / "dashboard.lock").exists()

    def test_unverified_outputs_recorded(self, mod):
        path = mod.update_dashboard("demo", "skill-1", SAMPLE_SKILLS, False)
        fm = mod.parse_dashboard_frontmatter(Path(path).read_text())
        assert fm["skills"]["skill-1"]["outputs_verified"] is False


# ── load_registry ────────────────────────────────────────────────────────


class TestLoadRegistry:
    def test_loads_yaml(self, mod, tmp_path):
        reg = tmp_path / "reg.yaml"
        reg.write_text("skills:\n  - id: a\n")
        data = mod.load_registry(reg)
        assert data["skills"][0]["id"] == "a"

    def test_empty_file(self, mod, tmp_path):
        reg = tmp_path / "empty.yaml"
        reg.write_text("")
        assert mod.load_registry(reg) == {}


# ── main (CLI integration) ──────────────────────────────────────────────


class TestMain:
    def _write_registry(self, mod, tmp_path):
        reg = tmp_path / "registry.yaml"
        reg.write_text(yaml.dump({"skills": SAMPLE_SKILLS}))
        mod.REGISTRY_PATH = reg
        return reg

    def test_unknown_skill_exits_cleanly(self, mod, tmp_path):
        self._write_registry(mod, tmp_path)
        with patch("sys.argv", ["prog", "--skill-name", "nonexistent", "--qs-name", "demo"]):
            mod.main()

    def test_known_skill_creates_dashboard(self, mod, tmp_path):
        self._write_registry(mod, tmp_path)
        out_dir = tmp_path / ".rhoai-qs" / "demo" / "flow"
        out_dir.mkdir(parents=True)
        out_file = out_dir / "output-1.md"
        out_file.write_text("content")

        skills = SAMPLE_SKILLS.copy()
        skills[0] = {**skills[0], "expected_outputs": [{"path": str(out_file)}]}
        reg = tmp_path / "registry.yaml"
        reg.write_text(yaml.dump({"skills": skills}))
        mod.REGISTRY_PATH = reg

        with patch("sys.argv", ["prog", "--skill-name", "skill-1", "--qs-name", "demo"]):
            mod.main()
        assert (tmp_path / ".rhoai-qs" / "demo" / "flow" / "dashboard.md").exists()

    def test_missing_registry_exits(self, mod, tmp_path):
        mod.REGISTRY_PATH = tmp_path / "no-such-file.yaml"
        with patch("sys.argv", ["prog", "--skill-name", "skill-1", "--qs-name", "demo"]):
            with pytest.raises(FileNotFoundError):
                mod.main()
