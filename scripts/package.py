#!/usr/bin/env python3
"""Validate and package authored files using only the standard library."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/acceptance-testing"


def validate_package():
    manifest = json.loads((PLUGIN / "plugin.json").read_text())
    compatibility = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
    for key in ["name", "version", "author", "license", "repository"]:
        assert manifest[key] == compatibility[key], f"Manifest mismatch: {key}"
    assert (ROOT / "LICENSE").is_file(), "Missing root license"
    assert (PLUGIN / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes(), "License mismatch"
    assert compatibility["skills"] == "./skills/"
    assert len(list((PLUGIN / "skills").glob("*/SKILL.md"))) == 6
    for skill in (PLUGIN / "skills").glob("*/SKILL.md"):
        text = skill.read_text()
        assert text.startswith("---\n") and f"name: {skill.parent.name}" in text
        assert (skill.parent / "agents/openai.yaml").is_file()
        for match in re.findall(r"\]\(([^)]+)\)", text):
            if "://" not in match:
                target = (skill.parent / match.split("#")[0]).resolve()
                assert target.is_relative_to(PLUGIN) and target.exists(), f"Broken reference: {skill} {match}"
    marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
    assert (ROOT / marketplace["plugins"][0]["source"]["path"]).resolve() == PLUGIN
    return manifest


def files(base):
    return sorted(p for p in base.rglob("*") if p.is_file() and not p.is_symlink()
                  and "__pycache__" not in p.parts and p.suffix != ".pyc" and p.name != ".DS_Store")


def main():
    manifest = validate_package()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / f"acceptance-testing-{manifest['version']}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in files(PLUGIN):
            bundle.write(path, path.relative_to(PLUGIN))
    marketplace_archive = dist / f"acceptance-testing-marketplace-{manifest['version']}.zip"
    with zipfile.ZipFile(marketplace_archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in files(PLUGIN):
            bundle.write(path, path.relative_to(ROOT))
        for path in [ROOT / ".agents/plugins/marketplace.json", ROOT / "README.md",
                     ROOT / "LICENSE", ROOT / "CONTRIBUTING.md", ROOT / "AGENTS.md"]:
            bundle.write(path, path.relative_to(ROOT))
        for path in files(ROOT / "docs"):
            bundle.write(path, path.relative_to(ROOT))
    sums = []
    for path in [archive, marketplace_archive]:
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
        print(f"{path} ({path.stat().st_size} bytes)")
    (dist / "SHA256SUMS").write_text("\n".join(sums) + "\n")


if __name__ == "__main__":
    main()
