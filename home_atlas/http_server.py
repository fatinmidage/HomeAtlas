from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from home_atlas.config import get_settings
from home_atlas.db import create_db_engine, create_tables, seed_people_from_tokens, session_scope
from home_atlas.orchestrator import home_atlas
from home_atlas.security import HomeAtlasError, UnauthorizedError, resolve_actor_id


class HomeAtlasHandler(BaseHTTPRequestHandler):
    engine = None
    settings = None

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            token = _bearer_token(self.headers.get("Authorization"))
            with session_scope(self.engine) as session:
                actor_id = resolve_actor_id(session, token, self.settings.token_map)
                result = home_atlas(str(body.get("request", "")), session, actor_id)
            self._json({"result": result})
        except UnauthorizedError as exc:
            self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        except (HomeAtlasError, ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    return token if scheme.lower() == "bearer" else None


def main() -> None:
    settings = get_settings()
    engine = create_db_engine(settings)
    create_tables(engine)
    with session_scope(engine) as session:
        seed_people_from_tokens(session, settings.token_map)
    HomeAtlasHandler.engine = engine
    HomeAtlasHandler.settings = settings
    server = ThreadingHTTPServer((settings.host, settings.port), HomeAtlasHandler)
    print(f"HomeAtlas HTTP runner listening on http://{settings.host}:{settings.port}/mcp")
    server.serve_forever()


if __name__ == "__main__":
    main()

