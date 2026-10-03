"""The mem0 self-hosted server REST client (MB-2/MB-4/MB-5/MB-8).

Speaks the small REST subset the product uses (pinned upstream facts,
``mem0ai/mem0`` @ the recorded SHA): ``GET /docs`` (liveness), ``GET
/memories``, ``POST /memories``, ``POST /search``, ``GET
/configure/providers``, ``POST /configure`` (admin). Program access carries
the admin key in the ``X-API-Key`` header; the key reaches this client only
through a zero-arg getter so no secret is ever stored on, logged from, or
repr'd through this module.

The HTTP edge is stdlib ``urllib`` (model-provider probe form): the client
carries zero third-party dependencies. Failures are typed — unreachable,
server error (status kept), client error — because the pipelines' honest
semantics (memory absent ≠ error) are built on these types, never on bare
exceptions.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping, Sequence


class Mem0Unreachable(Exception):
    """The server did not answer (connection refused, DNS, timeout)."""


class Mem0ServerError(Exception):
    """The server answered with a 5xx (or the upstream LLM failed)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"mem0 server error {status}: {detail}")
        self.status = status
        self.detail = detail


class Mem0ClientError(Exception):
    """The server answered with a 4xx (our request was wrong)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"mem0 rejected the request ({status}): {detail}")
        self.status = status
        self.detail = detail


class Mem0Client:
    """One mem0 server endpoint. ``api_key_getter`` returns the admin key at
    call time; nothing keeps a reference to the key itself."""

    def __init__(self, base_url: str, api_key_getter: Callable[[], str],
                 *, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key_getter = api_key_getter
        self._timeout = timeout

    # -- request core -----------------------------------------------------------

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None,
                 *, auth: bool = True) -> Any:
        url = self._base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth:
            key = self._api_key_getter()
            if key:
                headers["X-API-Key"] = key
        request = urllib.request.Request(url, data=data, method=method)
        for name, value in headers.items():
            # direct assignment (not add_header): urllib's capitalize() would
            # rewrite the wire header case, and the server's admin path
            # matches ``X-API-Key`` exactly.
            request.headers[name] = value
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001 - the body is best-effort detail
                pass
            if 500 <= exc.code < 600:
                raise Mem0ServerError(exc.code, detail) from exc
            raise Mem0ClientError(exc.code, detail) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise Mem0Unreachable(f"mem0 server unreachable at {self._base_url}: {exc}") from exc
        if not body:
            return None
        return json.loads(body.decode("utf-8"))

    # -- the pinned surface -------------------------------------------------

    def docs_liveness(self) -> bool:
        """``GET /docs`` answers 200 — the dispatch's liveness probe."""
        self._request("GET", "/docs", auth=False)
        return True

    def bundled_providers(self) -> dict[str, Any]:
        """``GET /configure/providers``: the image's bundled LLM/embedder lists."""
        return self._request("GET", "/configure/providers")

    def configure(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /configure`` (admin): deep-merges ``config`` into the
        server's mem0 config and rebuilds the memory instance."""
        return self._request("POST", "/configure", dict(config))

    def add_messages(self, messages: Sequence[Mapping[str, str]], user_id: str,
                     *, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """``POST /memories``: one capture batch for one profile namespace."""
        body: dict[str, Any] = {"messages": [
            {"role": str(m["role"]), "content": str(m["content"])} for m in messages],
            "user_id": user_id}
        if metadata:
            body["metadata"] = dict(metadata)
        return self._request("POST", "/memories", body)

    def search(self, query: str, user_id: str, *, top_k: int = 10) -> dict[str, Any]:
        """``POST /search`` scoped to one profile namespace via ``filters``."""
        return self._request("POST", "/search",
                             {"query": query, "filters": {"user_id": user_id},
                              "top_k": top_k})

    def get_all(self, user_id: str) -> dict[str, Any]:
        """``GET /memories?user_id=``: the memory viewer's listing."""
        return self._request("GET", f"/memories?user_id={urllib.parse.quote(user_id, safe='')}")
