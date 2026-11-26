#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-lab Web 控制台服务端。

纯标准库实现（http.server / socketserver / json / tomllib / subprocess /
pathlib / threading），零第三方依赖。

用法::

    <python> web/server.py                     # 127.0.0.1:8770
    <python> web/server.py --port 8771         # 换端口
    <python> web/server.py --host 127.0.0.1    # 换监听地址（默认已是本机）

接口::

    GET  /                              静态页面（web/static/index.html）
    GET  /<静态文件>                    web/static/ 下的文件（禁止 .. 穿越）
    GET  /api/projects                  项目列表（projects/*.toml + manifest 进度）
    GET  /api/manifest/<project>        out/<project>/manifest.json 原样返回
    GET  /api/chapter/<project>/<no>    out/<project>/chapters/00001.txt
    GET  /api/log/<project>?tail=200    out/<project>/run.log 末尾 N 行
    POST /api/run                       {"project":..,"from":..,"to":..} 启动 runner
    POST /api/stop                      {"project":..} 停止 runner

所有 JSON 响应均为 UTF-8 + ``ensure_ascii=False``；错误统一
``{"error": "..."}`` 加合适状态码，任何异常都不会让服务崩溃。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import tomllib
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
PROJECTS_DIR = REPO_ROOT / "projects"
OUT_DIR = REPO_ROOT / "out"
RUNNER = REPO_ROOT / "src" / "runner.py"
PYTHON = sys.executable or "python"

# 项目名会拼进 out/<project>/... 路径，必须是安全的 ASCII 标识符。
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}

# 本服务启动的 runner 进程表：project -> Popen
RUNNING: dict[str, subprocess.Popen] = {}
RUNNING_LOCK = threading.Lock()


class BadRequest(Exception):
    """请求体/参数不合法，对应 HTTP 400。"""


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _as_text(value) -> str | None:
    """把 TOML/JSON 里的值宽松地转成非空字符串。"""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _as_int(value, default=None):
    """宽松取整数；bool / 小数 / 非法字符串一律回退 default。"""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else default
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[+-]?\d+", text):
            return int(text)
    return default


def _read_manifest_lenient(project: str):
    """读 manifest.json；不存在或坏掉都返回 None（用于项目列表）。"""
    path = OUT_DIR / project / "manifest.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _prune_running() -> None:
    """清掉已经自己跑完的 runner 记录。"""
    with RUNNING_LOCK:
        dead = [name for name, proc in RUNNING.items() if proc.poll() is not None]
        for name in dead:
            RUNNING.pop(name, None)


def _tail_lines(path: Path, limit: int) -> list[str]:
    """读文件末尾 limit 行（限制读取量，避免几 MB 日志全量读入）。"""
    if limit <= 0 or not path.is_file():
        return []
    try:
        size = path.stat().st_size
        read_bytes = min(size, max(256 * 1024, limit * 2048))
        with path.open("rb") as handle:
            if size > read_bytes:
                handle.seek(size - read_bytes)
                chunk = handle.read()
                newline = chunk.find(b"\n")
                if newline >= 0:
                    chunk = chunk[newline + 1:]
            else:
                chunk = handle.read()
    except OSError:
        return []
    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return lines[-limit:] if limit < len(lines) else lines


def _project_toml_sections(toml_path: Path) -> tuple[dict, dict]:
    """返回 ([project] 段, 整个 toml 顶层字典)。"""
    raw = toml_path.read_text(encoding="utf-8-sig")
    data = tomllib.loads(raw)
    if not isinstance(data, dict):
        return {}, {}
    section = data.get("project")
    if not isinstance(section, dict):
        section = {}
    return section, data


def _pick(section: dict, top: dict, key: str):
    """优先 [project] 段，其次顶层同名键（兼容省略 [project] 头写法）。"""
    if key in section:
        return section[key]
    value = top.get(key)
    if isinstance(value, dict):
        return None
    return value


def _project_summary(toml_path: Path) -> dict:
    """把一个 projects/*.toml 变成 /api/projects 的一项，缺字段全部容错。"""
    stem = toml_path.stem
    entry = {
        "name": stem,
        "title": stem,
        "genre": None,
        "chapters": None,
        "words_per_chapter": None,
        "style": None,
        "model": None,
        "written": 0,
        "total": None,
        "logline": None,
        "running": False,
    }
    try:
        section, top = _project_toml_sections(toml_path)
        toml_name = _as_text(_pick(section, top, "name"))
        if toml_name and PROJECT_RE.match(toml_name):
            entry["name"] = toml_name
        entry["title"] = _as_text(_pick(section, top, "title")) or entry["name"]
        entry["genre"] = _as_text(_pick(section, top, "genre"))
        entry["style"] = _as_text(_pick(section, top, "style"))
        entry["model"] = _as_text(_pick(section, top, "model"))
        entry["logline"] = _as_text(_pick(section, top, "logline"))
        entry["chapters"] = _as_int(_pick(section, top, "chapters"))
        entry["words_per_chapter"] = _as_int(_pick(section, top, "words_per_chapter"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        entry["error"] = f"TOML 解析失败: {exc}"

    manifest = _read_manifest_lenient(entry["name"])
    entry["total"] = entry["chapters"]
    if isinstance(manifest, dict):
        total = _as_int(manifest.get("total"))
        written = _as_int(manifest.get("written"))
        if total is not None:
            entry["total"] = total
        if written is not None:
            entry["written"] = written
        entry["running"] = bool(manifest.get("running"))
        manifest_title = _as_text(manifest.get("title"))
        if manifest_title:
            entry["title"] = manifest_title
    return entry


def _safe_static_path(rel: str) -> Path | None:
    """把 URL 相对路径安全地映射到 web/static 下，拒绝穿越与绝对路径。"""
    if not rel:
        rel = "index.html"
    if "\x00" in rel:
        return None
    root = STATIC_DIR.resolve()
    try:
        candidate = (root / rel).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if candidate == root:
        candidate = root / "index.html"
    return candidate


# ---------------------------------------------------------------------------
# HTTP 处理器
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "novel-lab-web/1.0"
    protocol_version = "HTTP/1.1"

    # ---- 日志 -------------------------------------------------------------

    def log_message(self, fmt, *args):  # noqa: A003 - 父类约定
        sys.stderr.write(
            "[%s] %s %s\n"
            % (time.strftime("%H:%M:%S"), self.address_string(), fmt % args)
        )
        sys.stderr.flush()

    # ---- 响应 -------------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD" and body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    # ---- 分发 -------------------------------------------------------------

    def do_GET(self):  # noqa: N802 - 父类约定
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            self._route_get(path, query)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # 兜底：任何异常都回 JSON，不让服务挂掉
            self.log_error("GET %s 处理异常: %s", self.path, exc)
            try:
                self._json(500, {"error": f"服务内部错误: {exc}"})
            except Exception:
                pass

    def do_HEAD(self):  # noqa: N802 - 父类约定
        self.do_GET()

    def do_POST(self):  # noqa: N802 - 父类约定
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            try:
                body = self._read_json_body()
            except BadRequest as exc:
                return self._json(400, {"error": str(exc)})
            if path == "/api/run":
                return self._api_run(body)
            if path == "/api/stop":
                return self._api_stop(body)
            return self._json(404, {"error": f"未知接口: {path}"})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            self.log_error("POST %s 处理异常: %s", self.path, exc)
            try:
                self._json(500, {"error": f"服务内部错误: {exc}"})
            except Exception:
                pass

    def _route_get(self, path: str, query: dict) -> None:
        if path in ("/api/projects", "/api/projects/"):
            return self._api_projects()

        if path == "/api/log" or path.startswith("/api/log/"):
            project = path[len("/api/log/"):].strip("/") if path.startswith("/api/log/") else ""
            return self._api_log(project, query)

        if path.startswith("/api/manifest/"):
            project = path[len("/api/manifest/"):].strip("/")
            if not project or "/" in project:
                return self._json(400, {"error": "路径应为 /api/manifest/<project>"})
            return self._api_manifest(project)

        if path.startswith("/api/chapter/"):
            rest = path[len("/api/chapter/"):].strip("/")
            parts = rest.split("/")
            if len(parts) != 2:
                return self._json(400, {"error": "路径应为 /api/chapter/<project>/<no>"})
            return self._api_chapter(parts[0], parts[1])

        if path.startswith("/api/"):
            return self._json(404, {"error": f"未知接口: {path}"})

        return self._serve_static(path)

    def _read_json_body(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else 0
        except (TypeError, ValueError):
            raise BadRequest("Content-Length 不是合法整数")
        if length <= 0:
            raise BadRequest("请求体为空，需要 JSON 对象")
        if length > 2_000_000:
            raise BadRequest("请求体过大（上限 2MB）")
        data = self.rfile.read(length)
        if len(data) != length:
            raise BadRequest("请求体读取不完整")
        try:
            payload = json.loads(data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            raise BadRequest("请求体不是合法 UTF-8")
        except json.JSONDecodeError as exc:
            raise BadRequest(f"请求体不是合法 JSON: {exc}")
        if not isinstance(payload, dict):
            raise BadRequest("请求体必须是 JSON 对象")
        return payload

    # ---- 静态文件 ---------------------------------------------------------

    def _serve_static(self, path: str) -> None:
        rel = path.lstrip("/")
        if path.endswith("/"):
            rel = (rel + "index.html").lstrip("/")
        target = _safe_static_path(rel)
        if target is None:
            return self._json(404, {"error": "not found"})
        if not target.is_file():
            body = "404 Not Found\n".encode("utf-8")
            return self._send(404, body, "text/plain; charset=utf-8")
        try:
            data = target.read_bytes()
        except OSError as exc:
            return self._json(500, {"error": f"读取静态文件失败: {exc}"})
        content_type = MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
        return self._send(200, data, content_type, cache="no-cache")

    # ---- GET /api/projects -------------------------------------------------

    def _api_projects(self) -> None:
        projects: list[dict] = []
        if PROJECTS_DIR.is_dir():
            try:
                toml_files = sorted(PROJECTS_DIR.glob("*.toml"), key=lambda p: p.name.lower())
            except OSError:
                toml_files = []
            for toml_path in toml_files:
                try:
                    projects.append(_project_summary(toml_path))
                except Exception as exc:  # 单个坏文件不能拖垮整个列表
                    self.log_error("解析 %s 失败: %s", toml_path.name, exc)
        self._json(200, {"projects": projects})

    # ---- GET /api/manifest/<project> ---------------------------------------

    def _api_manifest(self, project: str) -> None:
        if not PROJECT_RE.match(project):
            return self._json(400, {"error": f"项目名不合法: {project!r}"})
        path = OUT_DIR / project / "manifest.json"
        if not path.is_file():
            return self._json(
                404,
                {"error": f"找不到 manifest: out/{project}/manifest.json（流水线还没写这个项目）"},
            )
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            return self._json(500, {"error": f"读取 manifest 失败: {exc}"})
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._json(500, {"error": f"manifest.json 不是合法 JSON: {exc}"})
        return self._json(200, data)

    # ---- GET /api/chapter/<project>/<no> -----------------------------------

    def _api_chapter(self, project: str, no_raw: str) -> None:
        if not PROJECT_RE.match(project):
            return self._json(400, {"error": f"项目名不合法: {project!r}"})
        if not no_raw.isdigit() or int(no_raw) < 1:
            return self._json(400, {"error": f"章号必须是正整数: {no_raw!r}"})
        number = int(no_raw)
        path = OUT_DIR / project / "chapters" / f"{number:05d}.txt"
        if not path.is_file():
            return self._json(404, {"error": f"章节不存在: 第 {number} 章"})
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            return self._json(500, {"error": f"读取章节失败: {exc}"})
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return self._json(200, {"no": number, "text": text})

    # ---- GET /api/log/<project>?tail=200 ----------------------------------

    def _api_log(self, project: str, query: dict) -> None:
        if not PROJECT_RE.match(project):
            return self._json(400, {"error": f"项目名不合法: {project!r}"})
        tail_raw = query.get("tail", ["200"])[0]
        try:
            tail = int(tail_raw)
        except (TypeError, ValueError):
            return self._json(400, {"error": f"tail 必须是整数: {tail_raw!r}"})
        tail = max(1, min(tail, 5000))
        lines = _tail_lines(OUT_DIR / project / "run.log", tail)
        return self._json(200, {"lines": lines})

    # ---- POST /api/run -----------------------------------------------------

    def _api_run(self, body: dict) -> None:
        project_raw = body.get("project")
        if not isinstance(project_raw, str) or not PROJECT_RE.match(project_raw.strip()):
            return self._json(
                400,
                {"error": "project 不合法，需要 1-64 位字母/数字/下划线/连字符"},
            )
        project = project_raw.strip()
        start = _as_int(body.get("from", 1))
        stop = _as_int(body.get("to"))
        if start is None:
            start = 1
        if start < 1 or stop is None or stop < start:
            return self._json(
                400,
                {"error": "参数不合法：from 必须是正整数，to 必须是 >= from 的正整数"},
            )

        _prune_running()
        with RUNNING_LOCK:
            proc = RUNNING.get(project)
        if proc is not None and proc.poll() is None:
            return self._json(409, {"error": "already running"})

        if not RUNNER.is_file():
            return self._json(
                500,
                {"error": f"runner 不存在: {RUNNER}（等 src/runner.py 就绪后再启动）"},
            )
        if not Path(PYTHON).is_file():
            return self._json(500, {"error": f"python 解释器不存在: {PYTHON}"})

        log_path = OUT_DIR / project / "run.log"
        cmd = [
            PYTHON,
            str(RUNNER),
            "--project",
            project,
            "--from",
            str(start),
            "--to",
            str(stop),
        ]
        env = os.environ.copy()
        # 让 runner 的 stdout/stderr 稳定输出 UTF-8，避免 Windows 下按 GBK
        # 写进 run.log 后接口读出乱码。
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("ab", buffering=0) as log_file:
                header = (
                    f"[web] {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 project={project} "
                    f"from={start} to={stop}\n"
                ).encode("utf-8")
                log_file.write(header)
                kwargs = {
                    "cwd": str(REPO_ROOT),
                    "stdin": subprocess.DEVNULL,
                    "stdout": log_file,
                    "stderr": subprocess.STDOUT,
                    "close_fds": True,
                    "env": env,
                }
                if os.name == "nt":
                    flags = 0
                    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    kwargs["creationflags"] = flags
                else:
                    # POSIX：独立会话，服务退出后 runner 不被连带杀掉
                    kwargs["start_new_session"] = True
                proc = subprocess.Popen(cmd, **kwargs)
        except OSError as exc:
            return self._json(500, {"error": f"启动 runner 失败: {exc}"})

        with RUNNING_LOCK:
            RUNNING[project] = proc
        self.log_message(
            "启动 runner project=%s pid=%s from=%s to=%s", project, proc.pid, start, stop
        )
        return self._json(
            200,
            {
                "pid": proc.pid,
                "project": project,
                "from": start,
                "to": stop,
                "log": f"out/{project}/run.log",
            },
        )

    # ---- POST /api/stop ----------------------------------------------------

    def _api_stop(self, body: dict) -> None:
        project_raw = body.get("project")
        if not isinstance(project_raw, str) or not PROJECT_RE.match(project_raw.strip()):
            return self._json(
                400,
                {"error": "project 不合法，需要 1-64 位字母/数字/下划线/连字符"},
            )
        project = project_raw.strip()
        _prune_running()
        with RUNNING_LOCK:
            proc = RUNNING.get(project)
        if proc is None or proc.poll() is not None:
            with RUNNING_LOCK:
                RUNNING.pop(project, None)
            return self._json(404, {"error": "not running"})

        pid = proc.pid
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        except OSError as exc:
            with RUNNING_LOCK:
                RUNNING.pop(project, None)
            return self._json(500, {"error": f"停止失败: {exc}"})
        with RUNNING_LOCK:
            RUNNING.pop(project, None)
        self.log_message("停止 runner project=%s pid=%s", project, pid)
        return self._json(200, {"stopped": True, "pid": pid})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        """客户端提前断开（keep-alive 连接被关闭）是正常现象，不打印 traceback。"""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------


def _reconfigure_stdio() -> None:
    """控制台编码不合适时不因为打印中文而崩（只降级错误处理，不改编码）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdio()
    parser = argparse.ArgumentParser(
        description="novel-lab Web 控制台（纯标准库，零第三方依赖）"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1（只本机访问）"
    )
    parser.add_argument("--port", type=int, default=8770, help="监听端口，默认 8770")
    parser.add_argument("--quiet", action="store_true", help="不打印每个请求的访问日志")
    args = parser.parse_args(argv)

    if not (0 < args.port < 65536):
        print(f"端口不合法: {args.port}", file=sys.stderr)
        return 2
    if args.quiet:
        Handler.log_message = lambda self, fmt, *a: None  # type: ignore[assignment]

    try:
        httpd = Server((args.host, args.port), Handler)
    except OSError as exc:
        print(f"无法监听 {args.host}:{args.port} —— {exc}", file=sys.stderr)
        return 2

    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"novel-lab Web 控制台已启动: http://{shown_host}:{args.port}/")
    print(f"  仓库根目录: {REPO_ROOT}")
    print(f"  Python:     {PYTHON}")
    print(f"  静态目录:   {STATIC_DIR}")
    print(
        "  runner:     "
        + (str(RUNNER) if RUNNER.is_file() else f"{RUNNER}（尚未就绪，POST /api/run 会返回 500）")
    )
    print("  按 Ctrl+C 停止服务（已启动的 runner 进程不会被连带杀掉）")

    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在关闭服务……")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
