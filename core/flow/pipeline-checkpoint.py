#!/usr/bin/env python3
"""Pipeline checkpoint — CLI tool invoked by skills at the end of their run.

Usage:
    python3 core/flow/pipeline-checkpoint.py --skill-name <id> --qs-name <slug>

Validates expected outputs and updates the markdown dashboard with progress.
Produces no stdout so the calling agent can fire-and-forget.
"""

import argparse
import fcntl
import glob
import logging
import os
import sys
import time

import yaml

from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = SCRIPT_DIR / "pipeline-registry.yaml"
FRESHNESS_WINDOW = 600  # seconds — outputs must be younger than this

LOG_DIR = Path(".tmp")
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "pipeline-checkpoint.log"),
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def load_registry(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def parse_dashboard_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from a dashboard markdown file."""
    if not text.startswith("---"):
        return {}
    end = text.index("---", 3)
    return yaml.safe_load(text[3:end]) or {}


def serialise_frontmatter(fm: dict) -> str:
    return "---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False).rstrip() + "\n---"


# ---------------------------------------------------------------------------
# Dashboard markdown renderer
# ---------------------------------------------------------------------------

def render_dashboard(qs_name: str, skills: list[dict], state: dict) -> str:
    """Render the full dashboard markdown from state + registry."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    total = len(skills)
    done_count = sum(
        1 for s in skills if state.get(s["id"], {}).get("status") == "done"
    )

    # Frontmatter
    fm = {"qs_name": qs_name, "created_at": state.get("created_at", now_str), "skills": {}}
    for s in skills:
        sid = s["id"]
        fm["skills"][sid] = state.get(sid, {"status": "pending"})

    # Progress bar — 24 chars wide
    bar_len = 24
    filled = round(bar_len * done_count / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = round(100 * done_count / total) if total else 0

    # Status table rows
    rows = []
    last_done_skill = None
    for s in skills:
        sid = s["id"]
        info = state.get(sid, {})
        status = info.get("status", "pending")
        completed_at = info.get("completed_at", "—")
        verified = info.get("outputs_verified")

        if status == "done":
            icon = "✅"
            last_done_skill = s
            outputs = s.get("expected_outputs", [])
            if outputs:
                first_out = outputs[0]
                out_path = first_out.get("path", "").replace("{qs-name}", qs_name) if isinstance(first_out, dict) else str(first_out).replace("{qs-name}", qs_name)
                out_link = f"[{os.path.basename(out_path)}](../../../{out_path})"
            else:
                out_link = "—"
            if verified is False:
                icon = "⚠️"
                out_link += " (Output not found! Verify outputs manually)"
        else:
            icon = "⏳"
            out_link = "—"
            completed_at = "—"

        rows.append(f"| {s.get('order', '')} | {sid} | {icon} {status} | {out_link} | {completed_at} |")

    # Determine next skill from pipeline chain
    next_skill = None
    if last_done_skill:
        next_id_yaml = last_done_skill.get("next_skill")
        if next_id_yaml:
            next_skill = next((s for s in skills if s["id"] == next_id_yaml), None)
    if next_skill is None:
        next_skill = next((s for s in skills if state.get(s["id"], {}).get("status") != "done"), None)

    # Review guidance
    review_section = ""
    if last_done_skill:
        guidance = last_done_skill.get("review_guidance", "").strip()
        if guidance:
            review_section = f"\n---\n\n## ⚠️ Review Before Continuing — {last_done_skill['id']}\n\n{guidance}\n"

    # Next step
    next_section = ""
    if next_skill:
        next_id = next_skill["id"]
        next_desc = next_skill.get("description", "")
        inputs = next_skill.get("expected_inputs", [])
        cmd_args = []
        for inp in inputs:
            if isinstance(inp, dict):
                name = inp.get("name", "")
                if name == "qs-name":
                    cmd_args.append(f"qs-name={qs_name}")
                else:
                    cmd_args.append(f"{name}=<{name}>")
        cmd = f"/{next_id} " + " ".join(cmd_args) if cmd_args else f"/{next_id}"
        next_section = f"\n---\n\n## ▶️ Next Step\n\n**{next_id}** — {next_desc}\n\n```\n{cmd}\n```\n"

    # Done message
    done_section = ""
    if done_count == total:
        done_section = "\n---\n\n## Pipeline Complete\n\nAll steps finished. Review the outputs above.\n"

    # Mermaid flowchart
    node_ids = [chr(65 + i) if i < 26 else f"N{i}" for i in range(len(skills))]
    chain = " --> ".join(
        f'{nid}["{s["id"]}"]' for nid, s in zip(node_ids, skills)
    )
    style_lines = []
    for i, s in enumerate(skills):
        info = state.get(s["id"], {})
        st = info.get("status", "pending")
        vf = info.get("outputs_verified")
        if st == "done" and vf:
            color = "fill:#2ea44f,color:#fff,stroke:#1a7f37" # green
        elif st == "done":
            color = "fill:#d4a017,color:#fff,stroke:#b8860b" # yellow
        else:
            color = "fill:#e0e0e0,color:#333,stroke:#bbb" # grey
        style_lines.append(f"    style {node_ids[i]} {color}")
    mermaid_block = (
        "```mermaid\nflowchart LR\n"
        f"    {chain}\n"
        + "\n".join(style_lines)
        + "\n```"
    )

    body = f"""\
<img src="../../../core/assets/dashboard-banner.svg" alt="Quickstart Factory — Red Hat OpenShift AI" width="100%"/>

# Pipeline Dashboard — {qs_name}

> Last updated: {now_str}

`{bar}` {pct}% ({done_count}/{total} steps)

## 🔀 Pipeline Flow

{mermaid_block}

## 📋 Pipeline Steps

| # | Step | Status | Output | Completed |
|---|------|--------|--------|-----------|
{chr(10).join(rows)}
{review_section}{next_section}{done_section}"""

    return serialise_frontmatter(fm) + "\n\n" + body


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_outputs(skill: dict, qs_name: str) -> bool:
    """Check that expected outputs exist and at least one match per pattern is fresh."""
    outputs = skill.get("expected_outputs", [])
    if not outputs:
        return True
    now = time.time()
    for out in outputs:
        pattern = out.get("path", "") if isinstance(out, dict) else str(out)
        pattern = pattern.replace("{qs-name}", qs_name)
        matches = glob.glob(pattern)
        if not matches:
            return False
        if not any(now - os.path.getmtime(m) <= FRESHNESS_WINDOW for m in matches):
            return False
    return True


# ---------------------------------------------------------------------------
# File-locked dashboard update
# ---------------------------------------------------------------------------

def update_dashboard(qs_name: str, skill_id: str, skills: list[dict], outputs_verified: bool):
    """Update (or create) the dashboard under file lock."""
    dashboard_dir = Path(f".rhoai-qs/{qs_name}/flow")
    dashboard_path = dashboard_dir / "dashboard.md"
    lock_dir = Path(f".tmp/{qs_name}")
    lock_path = lock_dir / "dashboard.lock"

    lock_dir.mkdir(parents=True, exist_ok=True)
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        # Read existing state or initialise
        if dashboard_path.exists():
            state = parse_dashboard_frontmatter(dashboard_path.read_text())
            skill_states = state.get("skills", {})
            created_at = state.get("created_at", now_str)
        else:
            skill_states = {}
            created_at = now_str

        # Ensure every skill has a state entry
        for s in skills:
            if s["id"] not in skill_states:
                skill_states[s["id"]] = {"status": "pending"}

        # Mark the completed skill
        skill_states[skill_id] = {
            "status": "done",
            "completed_at": now_str,
            "outputs_verified": outputs_verified,
        }

        full_state = {"created_at": created_at}
        full_state.update(skill_states)

        md = render_dashboard(qs_name, skills, full_state)
        dashboard_path.write_text(md)

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    return str(dashboard_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-name", required=True)
    parser.add_argument("--qs-name", required=True)
    args = parser.parse_args()

    skill_name = args.skill_name
    qs_name = args.qs_name

    log.info("Checkpoint called: skill=%s qs=%s", skill_name, qs_name)

    if not REGISTRY_PATH.exists():
        log.error("Registry not found: %s", REGISTRY_PATH)
        sys.exit(1)

    registry = load_registry(REGISTRY_PATH)
    skills = registry.get("skills", [])

    skill_entry = next((s for s in skills if s.get("id") == skill_name), None)
    if skill_entry is None:
        log.info("Skill %s not in pipeline, exiting", skill_name)
        return

    outputs_verified = validate_outputs(skill_entry, qs_name)
    log.info("Outputs verified: %s", outputs_verified)

    dashboard_path = update_dashboard(qs_name, skill_name, skills, outputs_verified)
    log.info("Dashboard updated: %s", dashboard_path)


if __name__ == "__main__":
    main()
