"""Check publishable files only. Does not inspect local archives or private data."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]

def main():
    result = subprocess.run(["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"],
                            cwd=ROOT, check=True, stdout=subprocess.PIPE)
    paths = sorted(set(name for name in result.stdout.decode().split("\0") if name))
    problems = []
    parsed = 0
    required = {"LICENSE", "README.md", "README.zh-CN.md", "SECURITY.md", "PROVENANCE.md",
                "CHANGELOG.md", "docs/FORMATS.md", "skills/wechat-local-vault/SKILL.md"}
    if not required <= set(paths):
        problems.append("Missing release documentation")
    prohibited = ("BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY", "/Users/keychron/",
                  "yichen-wechat-local-vault-safe", "wechat_frida_keys.log")
    for name in paths:
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            problems.append("Linked/non-regular release file: " + name)
            continue
        if any(part in {".git", ".test-artifacts", ".private", "__pycache__"} for part in path.relative_to(ROOT).parts):
            problems.append("Runtime directory included: " + name)
        if re.search(r"\.(?:db|sqlite)(?:-(?:wal|shm|journal))?$|(?:^|/)(?:keys|config|vault)\.json$", name):
            problems.append("Runtime data file included: " + name)
        if path.stat().st_size > 2 * 1024**2:
            problems.append("Oversized source artifact: " + name)
            continue
        text = path.read_text(encoding="utf-8")
        if name != "tools/check_release.py" and any(value in text for value in prohibited):
            problems.append("Private/restricted artifact marker: " + name)
        if re.search(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}", text):
            problems.append("Potential credential pattern: " + name)
        if path.suffix == ".py":
            tree = ast.parse(text, filename=name)
            parsed += 1
            if name.startswith("wechat_vault/"):
                imported = {node.module.split(".")[0] for node in ast.walk(tree)
                            if isinstance(node, ast.ImportFrom) and node.module and not node.level}
                imported |= {alias.name.split(".")[0] for node in ast.walk(tree)
                             if isinstance(node, ast.Import) for alias in node.names}
                if imported & {"socket", "requests", "urllib", "httpx", "subprocess", "frida", "Crypto"}:
                    problems.append("Unexpected acquisition/network dependency: " + name)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    namespace = {}
    for node in ast.parse((ROOT / "wechat_vault/__init__.py").read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets):
            namespace["__version__"] = ast.literal_eval(node.value)
    if project["project"]["version"] != namespace["__version__"]:
        problems.append("Version mismatch")
    if project["project"]["dependencies"]:
        problems.append("Core package unexpectedly has dependencies")
    print(json.dumps({"files": len(paths), "python_files": parsed,
                      "version": namespace["__version__"], "issues": problems}, indent=2))
    return 1 if problems else 0

if __name__ == "__main__":
    raise SystemExit(main())
