from __future__ import annotations

import base64
import json
import os
from typing import Any
from urllib import error, parse, request

from .mapper import OpenProjectMapper, link_href, link_id


class OpenProjectHttpError(RuntimeError):
    def __init__(self, status_code: int | None, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class OpenProjectNotFound(OpenProjectHttpError):
    def __init__(self, message: str = "OpenProject resource was not found.") -> None:
        super().__init__(404, message)


class _SameOriginRedirectHandler(request.HTTPRedirectHandler):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url

    def redirect_request(
        self,
        req: request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> request.Request | None:
        # urllib copies request headers when following redirects. Reject the
        # redirect before it can construct a request carrying Authorization to
        # a different origin.
        target_url = parse.urljoin(req.full_url, newurl)
        if not _same_origin(target_url, self.base_url):
            raise OpenProjectHttpError(
                None,
                "OpenProject redirect target is outside the configured base URL.",
            )
        return super().redirect_request(req, fp, code, msg, headers, target_url)


class OpenProjectClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_token: str | None = None,
        auth_scheme: str = "bearer",
        opener: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not base_url or not str(base_url).strip():
            raise ValueError("OpenProject base_url is required.")
        self.base_url = str(base_url).rstrip("/")
        parsed_base_url = parse.urlparse(self.base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError("OpenProject base_url must be an http or https origin.")
        self.api_token = api_token
        self.auth_scheme = auth_scheme
        self.opener = opener or request.build_opener(_SameOriginRedirectHandler(self.base_url))
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls, *, opener: Any | None = None) -> "OpenProjectClient":
        timeout = float(os.environ.get("FORMOWL_OPENPROJECT_TIMEOUT_SECONDS", "30"))
        return cls(
            base_url=os.environ["FORMOWL_OPENPROJECT_BASE_URL"],
            api_token=os.environ.get("FORMOWL_OPENPROJECT_API_TOKEN"),
            auth_scheme=os.environ.get("FORMOWL_OPENPROJECT_AUTH_SCHEME", "bearer"),
            opener=opener,
            timeout_seconds=timeout,
        )

    def get(self, path_or_href: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.url_for(path_or_href, params=params)
        headers = {
            "Accept": "application/hal+json, application/json",
            "User-Agent": "formowl-project-mcp/0.1",
        }
        auth_header = self._auth_header()
        if auth_header is not None:
            headers["Authorization"] = auth_header
        http_request = request.Request(url, headers=headers, method="GET")
        try:
            response = self._open(http_request)
            try:
                body = response.read()
            finally:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
        except error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except error.URLError as exc:
            raise OpenProjectHttpError(None, self._redact_credentials(str(exc.reason))) from exc
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OpenProjectHttpError(None, "OpenProject returned invalid JSON.") from exc
        return payload if isinstance(payload, dict) else {"value": payload}

    def url_for(self, path_or_href: str, params: dict[str, Any] | None = None) -> str:
        value = str(path_or_href)
        parsed = parse.urlparse(value)
        if parsed.scheme or parsed.netloc:
            url = parse.urljoin(f"{self.base_url}/", value)
            if not _same_origin(url, self.base_url):
                raise OpenProjectHttpError(
                    None,
                    "OpenProject link target is outside the configured base URL.",
                )
        elif value.startswith("/"):
            url = parse.urljoin(f"{self.base_url}/", value.lstrip("/"))
        else:
            url = parse.urljoin(f"{self.base_url}/api/v3/", value)
        clean_params = {key: val for key, val in (params or {}).items() if val is not None}
        if not clean_params:
            return url
        separator = "&" if parse.urlparse(url).query else "?"
        return f"{url}{separator}{parse.urlencode(clean_params, doseq=True)}"

    def _open(self, http_request: request.Request) -> Any:
        if hasattr(self.opener, "open"):
            return self.opener.open(http_request, timeout=self.timeout_seconds)
        return self.opener(http_request, timeout=self.timeout_seconds)

    def _auth_header(self) -> str | None:
        scheme = self.auth_scheme.lower().strip()
        if scheme not in {"bearer", "token", "basic", "none"}:
            raise ValueError(f"Unsupported OpenProject auth scheme: {self.auth_scheme}")
        if not self.api_token:
            return None
        if scheme in {"bearer", "token"}:
            return f"Bearer {self.api_token}"
        if scheme == "basic":
            encoded = base64.b64encode(f"apikey:{self.api_token}".encode("utf-8")).decode("ascii")
            return f"Basic {encoded}"
        if scheme == "none":
            return None
        raise ValueError(f"Unsupported OpenProject auth scheme: {self.auth_scheme}")

    def _http_error(self, exc: error.HTTPError) -> OpenProjectHttpError:
        message = exc.reason or f"OpenProject HTTP {exc.code}"
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        if isinstance(payload, dict) and payload.get("message"):
            message = str(payload["message"])
        message = self._redact_credentials(message)
        if exc.code == 404:
            return OpenProjectNotFound(message)
        return OpenProjectHttpError(exc.code, message)

    def _redact_credentials(self, message: str) -> str:
        redacted = str(message)
        if not self.api_token:
            return redacted
        token = str(self.api_token)
        basic_credential = base64.b64encode(f"apikey:{token}".encode("utf-8")).decode("ascii")
        credential_forms = {
            token,
            parse.quote(token, safe=""),
            basic_credential,
        }
        for credential in sorted(credential_forms, key=len, reverse=True):
            if credential:
                redacted = redacted.replace(credential, "[REDACTED]")
        return redacted


class OpenProjectAdapter:
    source_system = "openproject"

    def __init__(
        self,
        *,
        client: OpenProjectClient,
        source_instance: str = "openproject",
        mapper: OpenProjectMapper | None = None,
    ) -> None:
        self.client = client
        self.source_instance = source_instance
        self.mapper = mapper or OpenProjectMapper(
            source_instance=source_instance,
            base_url=client.base_url,
        )

    @classmethod
    def from_env(cls, *, opener: Any | None = None) -> "OpenProjectAdapter":
        client = OpenProjectClient.from_env(opener=opener)
        return cls(
            client=client,
            source_instance=os.environ.get("FORMOWL_OPENPROJECT_SOURCE_INSTANCE", "openproject"),
        )

    def search_work_items(self, input_data: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(input_data.get("query") or "")
        limit = int(input_data.get("limit") or 10)
        path = self._work_packages_path(
            input_data.get("project_ref"),
            project_ref_provided="project_ref" in input_data,
        )
        if path is None:
            return []
        params = {"pageSize": limit}
        filters = self._search_filters(input_data, query)
        if filters is not None:
            params["filters"] = filters
        collection = self.client.get(path, params=params)
        return self.mapper.map_search_results(collection, query=query, limit=limit)

    def get_work_item(self, source_ref: dict[str, Any]) -> dict[str, Any] | None:
        payload = self._get_work_package_payload(source_ref)
        return self.mapper.map_work_item(payload) if payload is not None else None

    def get_work_item_context(self, input_data: dict[str, Any]) -> dict[str, Any] | None:
        source_ref = input_data.get("source_ref", {})
        work_package = self._get_work_package_payload(source_ref)
        if work_package is None:
            return None
        source_id = str(work_package.get("id") or source_ref.get("source_id") or "unknown")
        quoted_source_id = _quote_path_segment(source_id)
        activities_collection = (
            self._collection_from_link(
                work_package,
                "activities",
                f"/api/v3/work_packages/{quoted_source_id}/activities",
            )
            if input_data.get("include_comments", True)
            or input_data.get("include_activities", True)
            else {"_embedded": {"elements": []}}
        )
        relations_collection = (
            self._collection_from_link(
                work_package,
                "relations",
                f"/api/v3/work_packages/{quoted_source_id}/relations",
            )
            if input_data.get("include_relations", True)
            else {"_embedded": {"elements": []}}
        )
        attachments_collection = (
            self._collection_from_link(
                work_package,
                "attachments",
                f"/api/v3/work_packages/{quoted_source_id}/attachments",
            )
            if input_data.get("include_attachments", True)
            else {"_embedded": {"elements": []}}
        )
        return {
            "work_item": self.mapper.map_work_item(work_package),
            "comments": self.mapper.map_comments(activities_collection)
            if input_data.get("include_comments", True)
            else [],
            "activities": self.mapper.map_activities(activities_collection)
            if input_data.get("include_activities", True)
            else [],
            "relations": self.mapper.map_relations(
                relations_collection,
                source_work_package_id=source_id,
            )
            if input_data.get("include_relations", True)
            else [],
            "attachments": self.mapper.map_attachments(
                attachments_collection,
                work_package_id=source_id,
            )
            if input_data.get("include_attachments", True)
            else [],
        }

    def list_work_item_activities(self, input_data: dict[str, Any]) -> list[dict[str, Any]]:
        source_id = _openproject_ref_id(input_data.get("source_ref", {}), "work_package")
        if source_id is None:
            return []
        limit = int(input_data.get("limit") or 50)
        collection = self.client.get(
            f"/api/v3/work_packages/{_quote_path_segment(source_id)}/activities"
        )
        return self.mapper.map_activities(collection)[:limit]

    def list_work_item_relations(self, input_data: dict[str, Any]) -> list[dict[str, Any]]:
        source_id = _openproject_ref_id(input_data.get("source_ref", {}), "work_package")
        if source_id is None:
            return []
        collection = self.client.get(
            f"/api/v3/work_packages/{_quote_path_segment(source_id)}/relations"
        )
        return self.mapper.map_relations(collection, source_work_package_id=source_id)

    def get_project_status(self, input_data: dict[str, Any]) -> dict[str, Any] | None:
        project = self._get_project_payload(input_data.get("project_ref", {}))
        if project is None:
            return None
        work_packages_path = link_href(project, "workPackages") or self._work_packages_path(
            self.mapper.map_project_ref(project)
        )
        limit = int(input_data.get("limit") or 100)
        work_packages = self.client.get(work_packages_path, params={"pageSize": limit})
        return self.mapper.map_project_status(
            project,
            work_packages,
            include_recent_updates=input_data.get("include_recent_updates", True),
        )

    def resolve_project_ref(self, project_ref: dict[str, Any]) -> dict[str, Any] | None:
        project = self._get_project_payload(project_ref)
        return self.mapper.map_project_ref(project) if project is not None else None

    def _get_work_package_payload(self, source_ref: dict[str, Any]) -> dict[str, Any] | None:
        source_id = _openproject_ref_id(source_ref, "work_package")
        if source_id is None:
            return None
        try:
            return self.client.get(f"/api/v3/work_packages/{_quote_path_segment(source_id)}")
        except OpenProjectNotFound:
            return None

    def _get_project_payload(self, project_ref: dict[str, Any]) -> dict[str, Any] | None:
        project_id = _openproject_ref_id(
            project_ref, "project", id_fields=("source_id", "source_key")
        )
        if project_id is None:
            return None
        try:
            return self.client.get(f"/api/v3/projects/{_quote_path_segment(project_id)}")
        except OpenProjectNotFound:
            return None

    def _collection_from_link(
        self, payload: dict[str, Any], link_name: str, fallback_path: str
    ) -> dict[str, Any]:
        return self.client.get(link_href(payload, link_name) or fallback_path)

    def _work_packages_path(
        self, project_ref: dict[str, Any] | None, *, project_ref_provided: bool = True
    ) -> str | None:
        if project_ref is None and not project_ref_provided:
            return "/api/v3/work_packages"
        project_id = _openproject_ref_id(
            project_ref, "project", id_fields=("source_id", "source_key")
        )
        if project_id is not None:
            return f"/api/v3/projects/{_quote_path_segment(project_id)}/work_packages"
        return None

    def _search_filters(self, input_data: dict[str, Any], query: str) -> str | None:
        filters = input_data.get("filters")
        if isinstance(filters, str):
            return filters
        if filters is not None:
            return json.dumps(filters, separators=(",", ":"))
        if not query:
            return None
        # OpenProject collection filters are JSON encoded into the query string.
        return json.dumps(
            [{"subject": {"operator": "~", "values": [query]}}],
            separators=(",", ":"),
        )


def _openproject_ref_id(
    source_ref: Any,
    expected_source_type: str,
    *,
    id_fields: tuple[str, ...] = ("source_id",),
) -> str | None:
    if not isinstance(source_ref, dict):
        return None
    if source_ref.get("source_system") != OpenProjectAdapter.source_system:
        return None
    if source_ref.get("source_type") != expected_source_type:
        return None
    for field in id_fields:
        source_id = source_ref.get(field)
        if isinstance(source_id, str) and source_id.strip():
            return source_id.strip()
    href_id = link_id(source_ref, "self")
    return href_id if href_id else None


def _quote_path_segment(value: str) -> str:
    # Source/project refs enter from MCP inputs, so "/" must not survive as a
    # path separator inside OpenProject API URLs.
    return parse.quote(value, safe="")


def _same_origin(url: str, base_url: str) -> bool:
    # HAL links may be absolute; keep the HTTP client bound to the configured
    # OpenProject origin instead of becoming a general URL fetcher.
    parsed_url = parse.urlparse(url)
    parsed_base = parse.urlparse(base_url)
    return (parsed_url.scheme, parsed_url.netloc) == (parsed_base.scheme, parsed_base.netloc)
