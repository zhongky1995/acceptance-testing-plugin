"""Small, local, versioned store. No network or third-party dependencies."""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.1"
EXCLUDED = {".git", ".acceptance", ".venv", "venv", "node_modules", "__pycache__",
            ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build", "coverage",
            ".next", ".nuxt", "target", ".DS_Store"}


class QAError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise QAError(f"无法读取 JSON：{path}: {exc}") from exc


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".qa-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            result.update(chunk)
    return result.hexdigest()


def project_snapshot(root, exclusions=(), max_files=10000, max_bytes=134217728):
    root = Path(root).resolve()
    if not root.is_dir():
        raise QAError("项目目录不存在")
    ignored_paths = [Path(p).resolve() for p in exclusions]
    hashes, reasons, ui_signals, total_bytes = [], [], [], 0
    for current, dirs, files in os.walk(root, followlinks=False):
        current = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and
                         not any((current / d).resolve().is_relative_to(p) for p in ignored_paths))
        for directory in dirs[:]:
            if (current / directory).is_symlink():
                reasons.append(f"符号链接目录未展开：{(current / directory).relative_to(root)}")
                dirs.remove(directory)
        for name in sorted(files):
            path = current / name
            if name in EXCLUDED or name.endswith(".pyc") or any(path.resolve().is_relative_to(p) for p in ignored_paths):
                continue
            if path.is_symlink():
                reasons.append(f"符号链接文件未展开：{path.relative_to(root)}")
                continue
            try:
                size = path.stat().st_size
                if len(hashes) >= max_files or total_bytes + size > max_bytes:
                    reasons.append("快照达到读取上限，不能据此判定证据仍有效")
                    return {"digest": digest(hashes), "complete": False, "files": len(hashes),
                            "bytes": total_bytes, "limitations": reasons, "excluded_names": sorted(EXCLUDED), "ui_signals": ui_signals}
                hashes.append([str(path.relative_to(root)), file_hash(path)])
                total_bytes += size
                if path.suffix.lower() in {".html", ".htm", ".tsx", ".jsx", ".vue", ".svelte", ".qml", ".storyboard", ".xib"}:
                    ui_signals.append(str(path.relative_to(root)))
                elif name == "package.json" and size < 1048576:
                    try:
                        package = load(path)
                        dependencies = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))
                        if dependencies & {"react", "vue", "svelte", "next", "nuxt", "electron", "@angular/core"}:
                            ui_signals.append(str(path.relative_to(root)))
                    except (QAError, AttributeError, TypeError):
                        pass
            except OSError as exc:
                reasons.append(f"读取失败：{path.relative_to(root)}: {exc}")
    return {"digest": digest(hashes), "complete": not reasons, "files": len(hashes),
            "bytes": total_bytes, "limitations": reasons, "excluded_names": sorted(EXCLUDED), "ui_signals": ui_signals}


def scan(root, exclusions=()):
    root = Path(root).resolve()
    snapshot = project_snapshot(root, exclusions)
    materials, manifests, tests = [], [], []
    count = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not (Path(current) / d).is_symlink()
                         and not any((Path(current) / d).resolve().is_relative_to(Path(p).resolve()) for p in exclusions))
        for name in sorted(files):
            path = Path(current) / name
            if path.is_symlink() or name in EXCLUDED:
                continue
            count += 1
            if count > 10000:
                break
            rel = str(path.relative_to(root))
            if name.lower().endswith((".md", ".mdx", ".rst")):
                materials.append(rel)
            if name in {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "pyproject.toml",
                        "requirements.txt", "poetry.lock", "uv.lock", "go.mod", "go.sum", "Cargo.toml",
                        "Cargo.lock", "Dockerfile", "compose.yaml", "docker-compose.yml"}:
                manifests.append(rel)
            if re.search(r"(^test_|_test\.|\.(test|spec)\.)", name):
                tests.append(rel)
        if count > 10000:
            break
    scripts = {}
    if (root / "package.json").is_file():
        try:
            package = load(root / "package.json")
            scripts = package.get("scripts", {})
        except QAError:
            pass
    tools = {}
    import shutil
    for tool in ["python3", "node", "npm", "pnpm", "go", "cargo", "docker"]:
        tools[tool] = shutil.which(tool)
    git = None
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3)
        if proc.returncode == 0:
            git = proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"schema_version": SCHEMA_VERSION, "project_root": str(root), "captured_at": now(),
            "snapshot": snapshot, "git_head": git, "materials": materials[:300],
            "dependency_files": manifests, "test_files": tests[:300], "declared_scripts": scripts,
            "available_executables": tools,
            "capabilities": {"command": True, "browser": "unknown", "computer_use": "unknown"},
            "notes": ["仅发现文件与工具，没有执行项目脚本、安装依赖或探测付费服务。",
                      "宿主、模型、浏览器、服务版本及外部配置需在 plan.environment 中补充；本地文件快照不能替代外部环境核验。"]}


def redact(text):
    text = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+", r"\1[REDACTED]", text)
    return re.sub(r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
