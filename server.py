from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.database import Database  # noqa: E402
from app.providers import ProviderError, list_models, merged_settings, public_settings  # noqa: E402
from app.service import CreatorService  # noqa: E402


DATABASE = Database(ROOT / "data" / "creator_hub.db")
SERVICE = CreatorService(DATABASE)
STATIC = ROOT / "static"
CREATOR_ROUTE = re.compile(r"^/api/creators/(\d+)(?:/(messages|import|draft|analyze))?$")


class Handler(BaseHTTPRequestHandler):
    server_version = "CreatorHub/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        log_path = ROOT / "logs" / "server.log"
        log_path.parent.mkdir(exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _body(self, max_size: int = 8_000_000) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > max_size:
            raise ValueError("提交内容过大")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("请求格式不正确")
        return value

    def _serve_static(self, route: str) -> None:
        relative = "index.html" if route in ("/", "") else route.lstrip("/")
        candidate = (STATIC / relative).resolve()
        if STATIC.resolve() not in candidate.parents and candidate != STATIC.resolve():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            candidate = STATIC / "index.html"
        content = candidate.read_bytes()
        mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            route = parsed.path
            if route == "/api/health":
                settings = merged_settings(DATABASE.get_settings())
                try:
                    models = list_models(settings)
                    model_status = "ready" if models else "no-model"
                    model_error = ""
                except ProviderError as exc:
                    models = []
                    model_status = "offline"
                    model_error = str(exc)
                self._json({
                    "ok": True,
                    "provider": settings.get("provider", "local"),
                    "model_status": model_status,
                    "models": models,
                    "model_error": model_error,
                })
                return
            if route == "/api/settings":
                self._json(public_settings(DATABASE.get_settings()))
                return
            if route == "/api/creators":
                query = parse_qs(parsed.query).get("q", [""])[0]
                self._json({"creators": DATABASE.list_creators(query)})
                return
            match = CREATOR_ROUTE.match(route)
            if match:
                creator_id = int(match.group(1))
                action = match.group(2)
                if action == "messages":
                    self._json({"messages": DATABASE.list_messages(creator_id)})
                elif action is None:
                    creator = DATABASE.get_creator(creator_id)
                    self._json(creator) if creator else self._error("达人不存在", 404)
                else:
                    self._error("接口不存在", 404)
                return
            self._serve_static(route)
        except Exception as exc:  # noqa: BLE001
            self._error(str(exc), 500)

    def do_POST(self) -> None:  # noqa: N802
        try:
            route = urlparse(self.path).path
            data = self._body(60_000_000 if route == "/api/import/batch" else 8_000_000)
            if route == "/api/creators":
                self._json(DATABASE.create_creator(data), 201)
                return
            if route == "/api/import/batch":
                self._json(SERVICE.import_batch(data.get("files", [])))
                return
            if route == "/api/import/whatsapp-visible":
                self._json(
                    SERVICE.import_visible_whatsapp(
                        str(data.get("chat_name", "")),
                        str(data.get("text", "")),
                    )
                )
                return
            if route == "/api/settings/test":
                saved = DATABASE.get_settings()
                saved.update({key: value for key, value in data.items() if value not in (None, "")})
                models = list_models(saved)
                self._json({"ok": True, "models": models})
                return
            match = CREATOR_ROUTE.match(route)
            if not match:
                self._error("接口不存在", 404)
                return
            creator_id = int(match.group(1))
            action = match.group(2)
            if action == "import":
                self._json(SERVICE.import_chat(creator_id, str(data.get("text", ""))))
            elif action == "draft":
                self._json(
                    SERVICE.create_draft(
                        creator_id,
                        str(data.get("intent", "")),
                        str(data.get("tone", "轻松自然")),
                    )
                )
            elif action == "analyze":
                self._json(SERVICE.analyse_creator(creator_id))
            else:
                self._error("接口不存在", 404)
        except (ValueError, KeyError, ProviderError) as exc:
            self._error(str(exc), 400)
        except Exception as exc:  # noqa: BLE001
            self._error(str(exc), 500)

    def do_PUT(self) -> None:  # noqa: N802
        try:
            route = urlparse(self.path).path
            data = self._body()
            if route == "/api/settings":
                allowed = {
                    "business_name", "provider", "base_url", "model", "api_key",
                    "remote_redaction", "fallback_local",
                }
                current = DATABASE.get_settings()
                updates = {key: value for key, value in data.items() if key in allowed}
                if not updates.get("api_key"):
                    updates.pop("api_key", None)
                current.update(updates)
                DATABASE.set_settings(current)
                self._json(public_settings(current))
                return
            match = CREATOR_ROUTE.match(route)
            if match and match.group(2) is None:
                self._json(DATABASE.update_creator(int(match.group(1)), data))
                return
            self._error("接口不存在", 404)
        except (ValueError, KeyError) as exc:
            self._error(str(exc), 400)
        except Exception as exc:  # noqa: BLE001
            self._error(str(exc), 500)

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            route = urlparse(self.path).path
            match = CREATOR_ROUTE.match(route)
            if match and match.group(2) is None:
                DATABASE.delete_creator(int(match.group(1)))
                self._json({"ok": True})
                return
            self._error("接口不存在", 404)
        except KeyError as exc:
            self._error(str(exc), 404)
        except Exception as exc:  # noqa: BLE001
            self._error(str(exc), 500)


def main() -> None:
    host = os.environ.get("CREATOR_HUB_HOST", "127.0.0.1")
    port = int(os.environ.get("CREATOR_HUB_PORT", "8765"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Creator Hub running at http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
