"""
S3 signature extraction: builds a structural fingerprint of a package's
source tree for later diffing against a prior version. Per PROJECT.md
Sec 5, S3 diffs "the new release's AST and dependency manifest" -- this
module produces the AST-derived half of that.

Ecosystem-specific parsers, both REAL AST parsing (not regex heuristics
pretending to be AST analysis):
  - pip (Python): stdlib `ast` module. Self-tested in this environment.
  - npm (JavaScript): `esprima` (pip install esprima) -- a genuine ESTree-
    format JS parser. NOT self-tested in the environment this was written
    in (no network access there to install esprima) -- implemented against
    esprima's documented API, needs a smoke test on a machine with it
    installed before being trusted.

Signature schema (per package version):
{
  "files": {relative_path: {"risky_calls": [...], "avg_line_length": float,
                             "loc": int, "parse_error": bool}},
  "install_hooks": {"preinstall": str|None, "install": str|None,
                     "postinstall": str|None, "prepare": str|None},
  "manifest_hash": str,  # hash of the full manifest file, catches any
                          # change even outside the tracked hook fields
}

Risky call categories detected (maps to Sec 5's "newly-introduced risky
capabilities"): eval_or_dynamic_code, child_process_or_subprocess,
network, env_access, obfuscated_literal.
"""

import ast as py_ast
import hashlib
import json
from pathlib import Path

TEXT_EXTENSIONS_NPM = {".js", ".mjs", ".cjs", ".ts"}
TEXT_EXTENSIONS_PIP = {".py"}

# A string literal this long, with a low proportion of common characters,
# is treated as a likely obfuscated/encoded blob (e.g. base64/hex payload)
# rather than ordinary source text. Heuristic, not a proof of obfuscation.
_OBFUSCATED_LITERAL_MIN_LEN = 200
_OBFUSCATED_LITERAL_MAX_COMMON_RATIO = 0.15  # max fraction of spaces/common punctuation allowed


def _looks_obfuscated(s: str) -> bool:
    if len(s) < _OBFUSCATED_LITERAL_MIN_LEN:
        return False
    common_chars = set(" \t\n.,;:'\"()[]{}")
    common_count = sum(1 for ch in s if ch in common_chars)
    return (common_count / len(s)) < _OBFUSCATED_LITERAL_MAX_COMMON_RATIO


def _avg_line_length(content: str) -> float:
    lines = content.split("\n")
    if not lines:
        return 0.0
    return len(content) / len(lines)


def _analyze_python_file(content: str) -> dict:
    risky = set()
    try:
        tree = py_ast.parse(content)
    except SyntaxError:
        return {"risky_calls": [], "avg_line_length": _avg_line_length(content),
                "loc": content.count("\n") + 1, "parse_error": True}

    for node in py_ast.walk(tree):
        if isinstance(node, ast_Call_types()):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in ("eval", "exec", "compile"):
                risky.add("eval_or_dynamic_code")
            if name in ("system", "popen", "call", "run", "Popen", "check_output", "check_call"):
                risky.add("child_process_or_subprocess")
        if isinstance(node, py_ast.Import):
            for alias in node.names:
                if alias.name in ("subprocess", "os"):
                    risky.add("child_process_or_subprocess")
                if alias.name in ("socket", "http", "http.client", "urllib", "urllib.request", "requests"):
                    risky.add("network")
        if isinstance(node, py_ast.ImportFrom):
            if node.module in ("subprocess",):
                risky.add("child_process_or_subprocess")
            if node.module in ("socket", "http.client", "urllib.request"):
                risky.add("network")
        if isinstance(node, py_ast.Attribute):
            if isinstance(node.value, py_ast.Name) and node.value.id == "os" and node.attr == "environ":
                risky.add("env_access")
        if isinstance(node, py_ast.Constant) and isinstance(node.value, str):
            if _looks_obfuscated(node.value):
                risky.add("obfuscated_literal")

    return {
        "risky_calls": sorted(risky),
        "avg_line_length": _avg_line_length(content),
        "loc": content.count("\n") + 1,
        "parse_error": False,
    }


def ast_Call_types():
    return (py_ast.Call,)


def _analyze_js_file(content: str) -> dict:
    """Real ESTree-format AST analysis via esprima. NOT self-tested in the
    environment this was authored in -- verify with a smoke test."""
    try:
        import esprima
    except ImportError:
        return {"risky_calls": [], "avg_line_length": _avg_line_length(content),
                "loc": content.count("\n") + 1, "parse_error": True,
                "note": "esprima not installed"}

    risky = set()
    try:
        tree = esprima.parseScript(content, options={"tolerant": True}).toDict()
    except Exception:
        try:
            tree = esprima.parseModule(content, options={"tolerant": True}).toDict()
        except Exception:
            return {"risky_calls": [], "avg_line_length": _avg_line_length(content),
                     "loc": content.count("\n") + 1, "parse_error": True}

    def walk(node):
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "CallExpression":
                callee = node.get("callee", {})
                callee_name = callee.get("name")
                if callee_name == "eval":
                    risky.add("eval_or_dynamic_code")
                if callee_name == "require":
                    args = node.get("arguments", [])
                    if args and args[0].get("type") == "Literal":
                        mod = args[0].get("value")
                        if mod == "child_process":
                            risky.add("child_process_or_subprocess")
                        if mod in ("http", "https", "net", "dgram"):
                            risky.add("network")
            if node_type == "NewExpression":
                callee = node.get("callee", {})
                if callee.get("name") == "Function":
                    risky.add("eval_or_dynamic_code")
            if node_type == "MemberExpression":
                obj = node.get("object", {})
                if obj.get("type") == "MemberExpression":
                    inner_obj = obj.get("object", {})
                    if inner_obj.get("name") == "process" and obj.get("property", {}).get("name") == "env":
                        risky.add("env_access")
                elif obj.get("name") == "process" and node.get("property", {}).get("name") == "env":
                    risky.add("env_access")
            if node_type == "Literal" and isinstance(node.get("value"), str):
                if _looks_obfuscated(node["value"]):
                    risky.add("obfuscated_literal")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(tree)
    return {
        "risky_calls": sorted(risky),
        "avg_line_length": _avg_line_length(content),
        "loc": content.count("\n") + 1,
        "parse_error": False,
    }


def _extract_npm_install_hooks(package_dir: Path) -> dict:
    hooks = {"preinstall": None, "install": None, "postinstall": None, "prepare": None}
    pkg_json_path = package_dir / "package.json"
    if not pkg_json_path.exists():
        return hooks
    try:
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return hooks
    scripts = data.get("scripts", {})
    for hook in hooks:
        hooks[hook] = scripts.get(hook)
    return hooks


def _extract_pip_install_hooks(package_dir: Path) -> dict:
    """Python packaging has no equivalent hook-name convention to npm's
    scripts -- MVP proxy: flag whether setup.py overrides the install/
    develop commands via cmdclass, which is the closest analogous
    arbitrary-code-at-install-time mechanism."""
    setup_py = package_dir / "setup.py"
    hooks = {"preinstall": None, "install": None, "postinstall": None, "prepare": None}
    if setup_py.exists():
        try:
            content = setup_py.read_text(encoding="utf-8", errors="replace")
            if "cmdclass" in content:
                hooks["install"] = "setup.py defines cmdclass (custom install/develop command)"
        except OSError:
            pass
    return hooks


def extract_signature(package_dir: str, ecosystem: str) -> dict:
    package_dir = Path(package_dir)
    extensions = TEXT_EXTENSIONS_NPM if ecosystem == "npm" else TEXT_EXTENSIONS_PIP
    analyze_fn = _analyze_js_file if ecosystem == "npm" else _analyze_python_file

    files = {}
    for path in package_dir.rglob("*"):
        if path.is_file() and path.suffix in extensions:
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel_path = str(path.relative_to(package_dir))
            files[rel_path] = analyze_fn(content)

    if ecosystem == "npm":
        install_hooks = _extract_npm_install_hooks(package_dir)
        manifest_path = package_dir / "package.json"
    else:
        install_hooks = _extract_pip_install_hooks(package_dir)
        manifest_path = package_dir / "setup.py"
        if not manifest_path.exists():
            manifest_path = package_dir / "pyproject.toml"

    manifest_hash = None
    if manifest_path.exists():
        try:
            manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        except OSError:
            pass

    declared_dependencies = _extract_declared_dependencies(package_dir, ecosystem)
    return {
        "files": files,
        "install_hooks": install_hooks,
        "manifest_hash": manifest_hash,
        "declared_dependencies": list(declared_dependencies),
    }
def _extract_declared_dependencies(package_dir: Path, ecosystem: str) -> set[str]:
    """Real, historically-motivated check: the event-stream/flatmap-stream
    2018 attack injected its payload via a brand-new DEPENDENCY, not a
    change to event-stream's own code -- AST diffing of the package's own
    files alone would have missed it entirely. This extracts the declared
    dependency name set so diff_signatures can flag newly-added deps."""
    if ecosystem == "npm":
        pkg_json = package_dir / "package.json"
        if not pkg_json.exists():
            return set()
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return set()
        deps = set(data.get("dependencies", {}).keys())
        deps |= set(data.get("optionalDependencies", {}).keys())
        return deps
    else:
        # pip: no single universal manifest format (setup.py can compute
        # install_requires dynamically, not just as a static literal) --
        # MVP limitation, stated honestly: only static requirements.txt
        # is parsed; setup.py-computed dependency lists are not.
        req_txt = package_dir / "requirements.txt"
        if not req_txt.exists():
            return set()
        try:
            lines = req_txt.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return set()
        deps = set()
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                name = line.split("=")[0].split(">")[0].split("<")[0].split("[")[0].strip()
                if name:
                    deps.add(name)
        return deps