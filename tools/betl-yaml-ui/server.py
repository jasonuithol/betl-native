"""
Tiny FastAPI backend for betl-yaml-ui.

  pip install fastapi uvicorn
  python server.py [--root DIR] [--port N]

Then open http://127.0.0.1:8765/

Endpoints:
  GET  /api/list?path=<rel>[&exts=.yml,.yaml]
                              list dirs + matching files under <root>/<rel>
  GET  /api/file?path=<rel>   return raw YAML text
  PUT  /api/file?path=<rel>   write raw YAML text (creates parents, overwrites)
  POST /api/validate          body {path}   → runs `betl validate`
  POST /api/convert           body {dtsx}   → runs dtsx2yaml; returns output path
  POST /api/test-connection   body {name,type,dsn} → run a SELECT-1 test pipeline
  POST /api/log               opaque text   → echo to server stderr

All <rel> paths are resolved relative to --root and rejected if they escape it.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import PlainTextResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
except ImportError:
    sys.exit("missing deps. run: pip install fastapi uvicorn")


HERE = Path(__file__).resolve().parent
ALLOWED_EXTS = {".yml", ".yaml"}
# Populated from CLI flags / env vars in main(). Workers spawned by
# uvicorn --reload re-read these env vars at module import time.
BETL_BIN: str | None = os.environ.get("BETL_BIN") or None
DTSX2YAML_BIN: str | None = os.environ.get("BETL_DTSX2YAML") or None


def discover_betl(root: Path) -> str | None:
    """Find the betl CLI. Order: BETL_BIN env, PATH, <root>/build*/betl."""
    if BETL_BIN and Path(BETL_BIN).exists():
        return BETL_BIN
    on_path = shutil.which("betl")
    if on_path:
        return on_path
    for cand in ("build/betl", "build-make/betl", "build-asan/betl", "build-tsan/betl"):
        p = root / cand
        if p.exists():
            return str(p)
    return None


def discover_dtsx2yaml(root: Path) -> str | None:
    """Find the dtsx2yaml binary. Order: env, repo publish dir."""
    if DTSX2YAML_BIN and Path(DTSX2YAML_BIN).exists():
        return DTSX2YAML_BIN
    cand = root / "tools/betl-dtsx2yaml/publish-linux-x64/Betl.Dtsx2Yaml"
    if cand.exists():
        return str(cand)
    return None

app = FastAPI(title="betl-yaml-ui")
# When uvicorn runs with --reload, the child worker re-imports this
# module and main() does not execute there — so the chosen --root has
# to survive via the environment.
ROOT: Path = Path(os.environ.get("BETL_YAML_UI_ROOT", str(HERE))).resolve()


def safe(rel: str) -> Path:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    p = (ROOT / rel).resolve()
    try:
        p.relative_to(ROOT)
    except ValueError:
        raise HTTPException(400, "path escapes root")
    return p


@app.get("/api/list")
def list_dir(path: str = "", exts: str = ""):
    p = safe(path)
    if not p.exists():
        raise HTTPException(404, "not found")
    if not p.is_dir():
        raise HTTPException(400, "not a directory")
    if exts:
        allowed = {("." + e.lstrip(".")).lower() for e in exts.split(",") if e.strip()}
    else:
        allowed = ALLOWED_EXTS
    dirs, files = [], []
    for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        rel = entry.relative_to(ROOT).as_posix()
        if entry.is_dir():
            dirs.append({"name": entry.name, "path": rel})
        elif entry.suffix.lower() in allowed:
            files.append({"name": entry.name, "path": rel, "size": entry.stat().st_size})
    return {
        "root": ROOT.as_posix(),
        "path": p.relative_to(ROOT).as_posix(),
        "dirs": dirs,
        "files": files,
    }


@app.get("/api/file")
def get_file(path: str):
    p = safe(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "not found")
    if p.suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(400, "only .yml/.yaml allowed")
    return PlainTextResponse(p.read_text(encoding="utf-8"))


@app.put("/api/file")
async def put_file(path: str, request: Request):
    p = safe(path)
    if p.suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(400, "only .yml/.yaml allowed")
    body = (await request.body()).decode("utf-8")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return {
        "ok": True,
        "path": p.relative_to(ROOT).as_posix(),
        "size": len(body),
    }


@app.post("/api/log")
async def log_event(request: Request):
    """Best-effort sink for client-side errors so they show up in the
    same terminal that's hosting the server."""
    body = (await request.body()).decode("utf-8", errors="replace")
    print(f"[ui] {body}", file=sys.stderr, flush=True)
    return {"ok": True}


def _run(cmd: list[str], env_extra: dict | None = None, timeout: int = 120) -> dict:
    """Execute `cmd`, capture stdout/stderr, never raise on non-zero rc."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    try:
        cp = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        return {
            "rc": cp.returncode,
            "stdout": cp.stdout,
            "stderr": cp.stderr,
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "rc": -1,
            "stdout": (e.stdout or "").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
            "stderr": f"timed out after {timeout}s",
            "cmd": cmd,
        }
    except FileNotFoundError as e:
        return {"rc": -2, "stdout": "", "stderr": str(e), "cmd": cmd}


@app.get("/api/tools")
def tools_info():
    """Report which external tools the server can drive. The client uses
    this to enable / disable the Validate and Convert buttons."""
    return {
        "betl": discover_betl(ROOT),
        "dtsx2yaml": discover_dtsx2yaml(ROOT),
    }


@app.post("/api/validate")
async def validate(request: Request):
    body = json.loads((await request.body()).decode("utf-8") or "{}")
    rel = body.get("path") or ""
    p = safe(rel)
    if not p.is_file():
        raise HTTPException(404, "file not found")
    betl = discover_betl(ROOT)
    if not betl:
        raise HTTPException(503, "betl binary not found — set BETL_BIN or pass --betl")
    # Some local betl builds need deps/lib/ on LD_LIBRARY_PATH for libyaml.
    deps_lib = (ROOT / "deps/lib").as_posix()
    env_extra = {"LD_LIBRARY_PATH": deps_lib + ":" + os.environ.get("LD_LIBRARY_PATH", "")}
    res = _run([betl, "validate", str(p)], env_extra=env_extra)
    return res


@app.post("/api/convert")
async def convert(request: Request):
    body = json.loads((await request.body()).decode("utf-8") or "{}")
    rel = body.get("dtsx") or ""
    p = safe(rel)
    if not p.is_file():
        raise HTTPException(404, "dtsx file not found")
    if p.suffix.lower() != ".dtsx":
        raise HTTPException(400, "input must be .dtsx")
    bin_path = discover_dtsx2yaml(ROOT)
    if not bin_path:
        raise HTTPException(503,
            "dtsx2yaml binary not found — build it (see tools/betl-dtsx2yaml/) "
            "or set BETL_DTSX2YAML")
    out_path = p.with_suffix(".betl.yml")
    res = _run([bin_path, str(p), "-o", str(out_path)])
    res["output"] = out_path.relative_to(ROOT).as_posix() if res["rc"] == 0 else None
    return res


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@app.post("/api/test-connection")
async def test_connection(request: Request):
    """Synthesize a tiny pipeline that opens this connection and runs
    `SELECT 1`, then run it via `betl run`. The result's rc + stdout +
    stderr tell the user whether the DSN and credentials are good.

    Body: {"name": "warehouse", "type": "postgres", "dsn": "..."}.
    Only postgres / mssql are testable today (sql.execute's dispatch). """
    body = json.loads((await request.body()).decode("utf-8") or "{}")
    name = (body.get("name") or "").strip()
    ctype = (body.get("type") or "").strip()
    dsn = body.get("dsn") or ""
    if not name or not _IDENT_RE.match(name):
        raise HTTPException(400, "connection name must be a simple identifier")
    if ctype not in ("postgres", "mssql"):
        raise HTTPException(
            400,
            f"connection type '{ctype}' is not testable (supported: postgres, mssql)"
        )
    if not isinstance(dsn, str) or not dsn:
        raise HTTPException(400, "connection has no dsn to test")

    betl = discover_betl(ROOT)
    if not betl:
        raise HTTPException(503, "betl binary not found — set BETL_BIN or pass --betl")

    # JSON-encoded scalars are also valid YAML, so this dodges every
    # quoting / escape ambiguity in the user-supplied DSN.
    yaml_text = (
        "betl: 1\n"
        "name: __ui_conn_test\n"
        "connections:\n"
        f"  {name}:\n"
        f"    type: {json.dumps(ctype)}\n"
        f"    dsn: {json.dumps(dsn)}\n"
        "pipeline:\n"
        "  - id: __ping\n"
        "    type: sql.execute\n"
        f"    connection: {json.dumps(name)}\n"
        '    sql: "SELECT 1"\n'
    )

    fd, tmp_path = tempfile.mkstemp(prefix="betl-test-conn-", suffix=".yml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml_text)
        deps_lib = (ROOT / "deps/lib").as_posix()
        env_extra = {
            "LD_LIBRARY_PATH": deps_lib + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        }
        res = _run([betl, "run", tmp_path], env_extra=env_extra, timeout=30)
    finally:
        try: os.unlink(tmp_path)
        except OSError: pass
    return res


# static viewer (registered last so /api/* routes win)
app.mount("/", StaticFiles(directory=HERE, html=True), name="ui")


def main():
    ap = argparse.ArgumentParser(description="betl-yaml-ui server")
    ap.add_argument(
        "--root",
        default=str(HERE.parent.parent),
        help="base directory the server may browse (default: repo root)",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument(
        "--reload",
        action="store_true",
        help="auto-reload on code edits (dev mode)",
    )
    ap.add_argument(
        "--betl",
        default=os.environ.get("BETL_BIN"),
        help="path to the betl CLI (default: $BETL_BIN, PATH, then <root>/build*/betl)",
    )
    ap.add_argument(
        "--dtsx2yaml",
        default=os.environ.get("BETL_DTSX2YAML"),
        help="path to the dtsx2yaml binary (default: $BETL_DTSX2YAML or "
             "<root>/tools/betl-dtsx2yaml/publish-linux-x64/Betl.Dtsx2Yaml)",
    )
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"--root is not a directory: {root}")
    os.environ["BETL_YAML_UI_ROOT"] = str(root)
    if args.betl:
        os.environ["BETL_BIN"] = args.betl
    if args.dtsx2yaml:
        os.environ["BETL_DTSX2YAML"] = args.dtsx2yaml
    global ROOT, BETL_BIN, DTSX2YAML_BIN
    ROOT = root
    BETL_BIN = args.betl or BETL_BIN
    DTSX2YAML_BIN = args.dtsx2yaml or DTSX2YAML_BIN

    print(f"betl-yaml-ui  ui={HERE}  root={ROOT}  ->  http://{args.host}:{args.port}/")
    if args.reload:
        uvicorn.run(
            "server:app",
            host=args.host,
            port=args.port,
            log_level="warning",
            reload=True,
            reload_dirs=[str(HERE)],
        )
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
