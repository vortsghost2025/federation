#!/usr/bin/env python3
"""Federation repository systems map generator.

Generates three artifacts in the repository root:

* FEDERATION_SYSTEMS_MAP.md – human‑readable markdown overview
* systems.json            – machine‑readable JSON dump
* generate_map.py          – this script (self‑documenting)

The script operates purely with the Python standard library and uses
``git ls-files`` to discover repository contents. It explicitly skips any
paths that contain ``node_modules``, ``.git`` or ``__pycache__``.

If a Python file cannot be parsed with ``ast`` (syntax error, encoding
issue, etc.) the script records a ``PARSE_ERROR`` entry instead of
crashing.

The generated markdown contains sections for:
  - Source modules (imports, functions)
  - Static assets (HTML/CSS/JS) – classified as STATIC_ASSET with live
    status UNKNOWN unless proven otherwise
  - Docs / config files – classified as DOC_OR_CONFIG
  - Test suite (test functions)
  - FastAPI endpoints (literal @app.<verb> decorators)
  - Import graph (who imports whom)
  - Parse errors

A concise summary with counts is printed to stdout after generation.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def _git_ls(pattern: str) -> List[str]:
    """Run ``git ls-files`` with the supplied pattern.

    Returns a list of matching paths, filtered to exclude any entry that
    contains ``node_modules``, ``.git`` or ``__pycache__``.
    """
    try:
        out = subprocess.check_output(["git", "ls-files", pattern], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return []
    paths = [p for p in out.splitlines() if p]
    excluded = ("node_modules", ".git", "__pycache__")
    return [p for p in paths if not any(kw in p for kw in excluded)]


def _safe_parse(src: str) -> Tuple[List[str], List[str]]:
    """Parse a Python source string safely.

    Returns ``(imports, functions)``.  If parsing fails both lists are empty.
    The caller should treat the file as a parse error in that case.
    """
    try:
        tree = ast.parse(src)
    except Exception:
        return [], []
    imports: List[str] = []
    functions: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imports.append(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
    # Deduplicate while preserving order
    seen = set()
    imports = [i for i in imports if not (i in seen or seen.add(i))]
    seen.clear()
    functions = [f for f in functions if not (f in seen or seen.add(f))]
    return imports, functions


def _extract_routes(src: str) -> List[Tuple[str, str]]:
    """Extract FastAPI routes from source code, ignoring docstrings and comments.

    Returns a list of ``(METHOD, PATH)`` tuples for real ``@app.<verb>("/path")``
    decorators found in code (not in documentation strings or comments).
    """
    routes: List[Tuple[str, str]] = []
    pattern = re.compile(r"@app\.(get|post|put|delete|websocket)\(\s*['\"]([^'\"]+)['\"]")
    in_block_string = False
    for line in src.splitlines():
        stripped = line.strip()
        # Toggle block string detection for triple‑quoted literals
        if stripped.startswith('"""') or stripped.startswith("'''"):
            # Count occurrences to handle opening and closing on same line
            triple_count = stripped.count('"""') + stripped.count("'''")
            if triple_count % 2 == 1:
                in_block_string = not in_block_string
            continue
        if in_block_string:
            continue
        # Skip line comments
        if stripped.startswith('#'):
            continue
        # Skip lines that appear to be code examples (contain backticks)
        if '`' in line:
            continue
        m = pattern.search(line)
        if m:
            routes.append((m.group(1).upper(), m.group(2)))
    return routes


def _extract_tests(src: str) -> List[str]:
    """Return test function identifiers from a test file.

    Captures any function named ``test*`` and any ``unittest.TestCase``
    method that starts with ``test``.
    """
    try:
        tree = ast.parse(src)
    except Exception:
        return []
    test_funcs: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
            test_funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                if getattr(base, "id", None) == "TestCase":
                    for sub in node.body:
                        if isinstance(sub, ast.FunctionDef) and sub.name.startswith("test"):
                            test_funcs.append(f"{node.name}.{sub.name}")
    return test_funcs

# ---------------------------------------------------------------------------
# Main generation routine
# ---------------------------------------------------------------------------
def main() -> None:
    repo_root = Path('.')

    # 1️⃣ Gather file lists via git
    py_files = _git_ls('*.py')
    test_files = _git_ls('test_*.py') + _git_ls('*_test.py')
    test_files = sorted(set(test_files))
    static_assets = (
        _git_ls('*.html') + _git_ls('*.css') + _git_ls('*.js')
    )
    static_assets = sorted(set(static_assets))
    doc_or_config = (
        _git_ls('*.md') +
        _git_ls('Dockerfile') +
        _git_ls('docker-compose.yml') +
        _git_ls('*.json') +
        _git_ls('*.yml') +
        _git_ls('*.yaml')
    )
    doc_or_config = sorted(set(doc_or_config) - set(static_assets) - set(py_files) - set(test_files))

    # Containers for collected data
    source_modules: List[Dict] = []
    api_routes: List[Dict] = []
    tests_index: List[Dict] = []
    import_graph: Dict[str, List[str]] = {}
    parse_errors: List[str] = []

    # 2️⃣ Process Python source modules (including potential test files later)
    for rel_path in py_files:
        abs_path = repo_root / rel_path
        try:
            content = abs_path.read_text(encoding='utf-8')
        except Exception:
            parse_errors.append(rel_path)
            continue
        imports, functions = _safe_parse(content)
        if not imports and not functions and ("def " in content or "class " in content):
            # File looks like code but failed to parse
            parse_errors.append(rel_path)
        source_modules.append({
            "path": rel_path,
            "imports": imports,
            "functions": functions,
        })
        import_graph[rel_path] = imports
        # Extract API routes from any source module
        for method, path in _extract_routes(content):
            api_routes.append({"method": method, "path": path, "module": rel_path})

    # 3️⃣ Process test files (they are also Python, but we treat them separately)
    for rel_path in test_files:
        abs_path = repo_root / rel_path
        try:
            content = abs_path.read_text(encoding='utf-8')
        except Exception:
            parse_errors.append(rel_path)
            continue
        test_funcs = _extract_tests(content)
        tests_index.append({"path": rel_path, "test_functions": test_funcs})
        # Record their imports as part of the graph
        imports, _ = _safe_parse(content)
        import_graph[rel_path] = imports

    # -----------------------------------------------------------------------
    # Build markdown output
    # -----------------------------------------------------------------------
    md: List[str] = ["# FEDERATION SYSTEMS MAP", ""]
    md.append("## 1️⃣ Source Modules")
    for mod in source_modules:
        imp = ", ".join(mod["imports"]) or "none"
        md.append(f"- `{mod['path']}` – imports: {imp}")
    md.append("")
    md.append("## 2️⃣ Static Assets (HTML/CSS/JS)")
    md.append("Classification: STATIC_ASSET – live status: UNKNOWN unless linked by a deployed route/page")
    for asset in static_assets:
        md.append(f"- `{asset}`")
    md.append("")
    md.append("## 3️⃣ Docs / Config Files")
    md.append("Classification: DOC_OR_CONFIG – not considered live usage")
    for doc in doc_or_config:
        md.append(f"- `{doc}`")
    md.append("")
    md.append("## 4️⃣ Test Suite")
    for t in tests_index:
        cnt = len(t["test_functions"])
        md.append(f"- `{t['path']}` – {cnt} test function(s)")
    md.append("")
    md.append("## 5️⃣ FastAPI Endpoints")
    for r in api_routes:
        md.append(f"- `{r['method']} {r['path']}` (defined in `{r['module']}`)")
    md.append("")
    md.append("## 6️⃣ Import Graph (who imports whom)")
    for file, deps in import_graph.items():
        dep_str = ", ".join(deps) or "no imports"
        md.append(f"- `{file}` → {dep_str}")
    md.append("")
    md.append("## 7️⃣ Parse Errors")
    for pe in parse_errors:
        md.append(f"- `{pe}` – PARSE_ERROR")

    # Write artifacts
    (repo_root / "FEDERATION_SYSTEMS_MAP.md").write_text("\n".join(md), encoding='utf-8')
    data = {
        "source_modules": source_modules,
        "static_assets": static_assets,
        "docs_or_config": doc_or_config,
        "tests": tests_index,
        "api_routes": api_routes,
        "import_graph": import_graph,
        "parse_errors": parse_errors,
    }
    (repo_root / "systems.json").write_text(json.dumps(data, indent=2), encoding='utf-8')

    # -----------------------------------------------------------------------
    # Summary printed to stdout
    # -----------------------------------------------------------------------
    print("SUMMARY")
    print(f"Python modules: {len(source_modules)}")
    print(f"Test files: {len(tests_index)}")
    print(f"Static assets: {len(static_assets)}")
    print(f"Docs / config files: {len(doc_or_config)}")
    print(f"API routes: {len(api_routes)}")
    print(f"Parse errors: {len(parse_errors)}")

if __name__ == "__main__":
    main()
