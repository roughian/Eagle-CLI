from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin


DEFAULT_BASE_URL = "http://localhost:41595"


class EagleApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass
class DetectionResult:
    base_url: str
    root_available: bool
    v1_available: bool
    v2_available: bool
    inferred_variant: str | None
    details: dict[str, Any]


class EagleClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 15.0,
        session: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session

    @property
    def session(self) -> Any | None:
        return self._session

    def detect(self) -> DetectionResult:
        details: dict[str, Any] = {}
        root_available = False
        v1_available = False
        v2_available = False

        root_result = self._probe("/")
        if root_result is not None:
            root_available = True
            details["root"] = root_result

        v1_result = self._probe("/api/application/info")
        if v1_result is not None:
            v1_available = True
            details["v1"] = v1_result

        v2_result = self._probe("/api/v2/app/info")
        if v2_result is not None:
            v2_available = True
            details["v2"] = v2_result

        inferred = None
        if v1_available:
            inferred = "v1"
        elif v2_available:
            inferred = "v2"
        elif root_available:
            inferred = "root"

        return DetectionResult(
            base_url=self.base_url,
            root_available=root_available,
            v1_available=v1_available,
            v2_available=v2_available,
            inferred_variant=inferred,
            details=details,
        )

    def app_info(self) -> dict[str, Any]:
        return self.get_json("/api/application/info")

    def library_info(self) -> dict[str, Any]:
        return self.get_json("/api/library/info")

    def library_history(self) -> dict[str, Any]:
        return self.get_json("/api/library/history")

    def library_switch(self, library_path: str) -> dict[str, Any]:
        return self.post_json("/api/library/switch", {"libraryPath": library_path})

    def library_icon_url(self, library_path: str) -> str:
        encoded = quote(library_path, safe="")
        return f"{self.base_url}/api/library/icon?libraryPath={encoded}"

    def library_icon_download(self, library_path: str, output_path: str) -> str:
        session = self.session
        url = self.library_icon_url(library_path)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if session is not None:
            response = session.get(url, timeout=self.timeout)
            response.raise_for_status()
            output.write_bytes(response.content)
            return str(output)
        output.write_bytes(self._curl_download(url))
        return str(output)

    def folder_list(self) -> dict[str, Any]:
        return self.get_json("/api/folder/list")

    def folder_recent(self) -> dict[str, Any]:
        return self.get_json("/api/folder/listRecent")

    def folder_create(self, folder_name: str, parent: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"folderName": folder_name}
        if parent:
            payload["parent"] = parent
        return self.post_json("/api/folder/create", payload)

    def folder_rename(self, folder_id: str, new_name: str) -> dict[str, Any]:
        return self.post_json("/api/folder/rename", {"folderId": folder_id, "newName": new_name})

    def folder_update(
        self,
        folder_id: str,
        *,
        new_name: str | None = None,
        new_description: str | None = None,
        new_color: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"folderId": folder_id}
        if new_name is not None:
            payload["newName"] = new_name
        if new_description is not None:
            payload["newDescription"] = new_description
        if new_color is not None:
            payload["newColor"] = new_color
        return self.post_json("/api/folder/update", payload)

    def item_list(self, **params: Any) -> dict[str, Any]:
        normalized = {key: value for key, value in params.items() if value not in (None, "", [], ())}
        return self.get_json("/api/item/list", params=normalized)

    def item_info(self, item_id: str) -> dict[str, Any]:
        return self.get_json("/api/item/info", params={"id": item_id})

    def item_thumbnail(self, item_id: str) -> dict[str, Any]:
        return self.get_json("/api/item/thumbnail", params={"id": item_id})

    def item_update(
        self,
        item_id: str,
        *,
        tags: list[str] | None = None,
        annotation: str | None = None,
        url: str | None = None,
        star: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": item_id}
        if tags is not None:
            payload["tags"] = tags
        if annotation is not None:
            payload["annotation"] = annotation
        if url is not None:
            payload["url"] = url
        if star is not None:
            payload["star"] = star
        return self.post_json("/api/item/update", payload)

    def item_add_from_path(
        self,
        path: str,
        *,
        name: str,
        website: str | None = None,
        tags: list[str] | None = None,
        annotation: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"path": path, "name": name}
        if website:
            payload["website"] = website
        if tags:
            payload["tags"] = tags
        if annotation:
            payload["annotation"] = annotation
        if folder_id:
            payload["folderId"] = folder_id
        return self.post_json("/api/item/addFromPath", payload)

    def item_add_from_paths(self, items: list[dict[str, Any]], folder_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"items": items}
        if folder_id:
            payload["folderId"] = folder_id
        return self.post_json("/api/item/addFromPaths", payload)

    def item_add_from_url(
        self,
        url: str,
        *,
        name: str,
        website: str | None = None,
        tags: list[str] | None = None,
        star: int | None = None,
        annotation: str | None = None,
        modification_time: int | None = None,
        folder_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"url": url, "name": name}
        if website:
            payload["website"] = website
        if tags:
            payload["tags"] = tags
        if star is not None:
            payload["star"] = star
        if annotation:
            payload["annotation"] = annotation
        if modification_time is not None:
            payload["modificationTime"] = modification_time
        if folder_id:
            payload["folderId"] = folder_id
        if headers:
            payload["headers"] = headers
        return self.post_json("/api/item/addFromURL", payload)

    def item_add_from_urls(self, items: list[dict[str, Any]], folder_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"items": items}
        if folder_id:
            payload["folderId"] = folder_id
        return self.post_json("/api/item/addFromURLs", payload)

    def item_add_bookmark(
        self,
        url: str,
        *,
        name: str,
        base64: str | None = None,
        tags: list[str] | None = None,
        modification_time: int | None = None,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"url": url, "name": name}
        if base64:
            payload["base64"] = base64
        if tags:
            payload["tags"] = tags
        if modification_time is not None:
            payload["modificationTime"] = modification_time
        if folder_id:
            payload["folderId"] = folder_id
        return self.post_json("/api/item/addBookmark", payload)

    def item_move_to_trash(self, item_ids: list[str]) -> dict[str, Any]:
        return self.post_json("/api/item/moveToTrash", {"itemIds": item_ids})

    def item_refresh_palette(self, item_id: str) -> dict[str, Any]:
        return self.post_json("/api/item/refreshPalette", {"id": item_id})

    def item_refresh_thumbnail(self, item_id: str) -> dict[str, Any]:
        return self.post_json("/api/item/refreshThumbnail", {"id": item_id})

    def raw_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any = None,
    ) -> dict[str, Any]:
        return self.request_json(method, path, params=params, payload=payload)

    def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request_json("GET", path, params=params)

    def post_json(self, path: str, payload: Any) -> dict[str, Any]:
        return self.request_json("POST", path, payload=payload)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any = None,
    ) -> dict[str, Any]:
        url = self._build_url(path)
        if params:
            url = self._append_params(url, params)
        headers: dict[str, str] = {}
        data: bytes | None = None

        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")

        session = self.session
        if session is not None:
            response = session.request(
                method=method.upper(),
                url=url,
                params=params,
                json=payload if payload is not None else None,
                data=None,
                headers=headers or None,
                timeout=self.timeout,
            )
            return self._parse_json_response(response)
        return self._curl_json(method.upper(), url, payload=payload)

    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def _probe(self, path: str) -> dict[str, Any] | None:
        url = self._build_url(path)
        try:
            session = self.session
            if session is not None:
                response = session.get(url, timeout=self.timeout)
                return self._parse_json_response(response)
            return self._curl_json("GET", url, payload=None)
        except Exception:
            return None

    def _append_params(self, url: str, params: dict[str, Any]) -> str:
        normalized = {key: value for key, value in params.items() if value not in (None, "", [], ())}
        if not normalized:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{urlencode(normalized, doseq=True)}"

    def _curl_json(self, method: str, url: str, *, payload: Any | None) -> dict[str, Any]:
        marker = "__CLI_ANYTHING_EAGLE_HTTP_STATUS__:"
        command = [
            "curl",
            "-sS",
            "--max-time",
            _format_timeout(self.timeout),
            "-X",
            method.upper(),
            "-H",
            "Accept: application/json",
            "--write-out",
            f"\n{marker}%{{http_code}}",
        ]
        if payload is not None:
            command.extend(
                [
                    "-H",
                    "Content-Type: application/json",
                    "--data-binary",
                    json.dumps(payload, ensure_ascii=False),
                ]
            )
        command.append(url)
        exit_code, output = _run_capture(command)
        if exit_code != 0:
            message = output.decode("utf-8", errors="replace").strip() or f"curl exited with status {exit_code}"
            raise EagleApiError(message)
        stdout = output.decode("utf-8", errors="replace")
        body, separator, status_text = stdout.rpartition(f"\n{marker}")
        if not separator:
            raise EagleApiError(f"Expected curl status marker for {url}")
        try:
            status_code = int(status_text.strip())
        except ValueError as exc:
            raise EagleApiError(f"Invalid curl status marker for {url}: {status_text!r}") from exc
        return self._parse_json_bytes(
            body.encode("utf-8"),
            url=url,
            status_code=status_code,
            reason=f"HTTP {status_code}",
        )

    def _curl_download(self, url: str) -> bytes:
        command = [
            "curl",
            "-fsSL",
            "--max-time",
            _format_timeout(self.timeout),
            url,
        ]
        exit_code, output = _run_capture(command)
        if exit_code != 0:
            message = output.decode("utf-8", errors="replace").strip() or f"curl exited with status {exit_code}"
            raise EagleApiError(message)
        return output

    def _parse_json_bytes(self, payload_bytes: bytes, *, url: str, status_code: int, reason: str) -> dict[str, Any]:
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise EagleApiError(
                f"Expected JSON response from {url}",
                status_code=status_code,
            ) from exc
        return self._coerce_payload(payload, url=url, status_code=status_code, reason=reason)

    def _parse_json_response(self, response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise EagleApiError(
                f"Expected JSON response from {response.url}",
                status_code=response.status_code,
            ) from exc
        return self._coerce_payload(payload, url=response.url, status_code=response.status_code, reason=response.reason)

    def _coerce_payload(self, payload: Any, *, url: str, status_code: int, reason: str) -> dict[str, Any]:
        if isinstance(payload, dict) and 200 <= status_code < 300 and payload.get("status") == "success":
            return payload

        message = reason or f"HTTP {status_code}"
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("status") or message
        raise EagleApiError(message, status_code=status_code, payload=payload)


def _requests_module() -> Any:
    import requests

    return requests


def _format_timeout(value: float) -> str:
    return f"{value:g}"


def _run_capture(command: list[str]) -> tuple[int, bytes]:
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - exercised via CLI smoke tests
        try:
            os.close(read_fd)
            os.dup2(write_fd, 1)
            os.dup2(write_fd, 2)
            os.close(write_fd)
            os.execvp(command[0], command)
        except Exception:
            os._exit(127)

    os.close(write_fd)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(read_fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    os.close(read_fd)
    _, status = os.waitpid(pid, 0)
    exit_code = os.waitstatus_to_exitcode(status)
    return exit_code, b"".join(chunks)
