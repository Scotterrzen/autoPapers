from __future__ import annotations

import json
import ssl
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


class HttpError(RuntimeError):
    """Raised when an HTTP request fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.error_code = error_code
        self.response_body = response_body


@dataclass(slots=True)
class HttpClient:
    timeout_seconds: int = 30
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    default_headers: dict[str, str] = field(
        default_factory=lambda: {"User-Agent": "autoPapers/0.1 (+https://local.autopapers)"}
    )

    def get_text(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> str:
        full_url = self._build_url(url, params)
        request = Request(full_url, headers=self._merge_headers(headers), method="GET")
        return self._request_text(request, full_url)

    def get_json(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        return json.loads(self.get_text(url, params=params, headers=headers))

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        merged_headers = self._merge_headers(headers)
        merged_headers.setdefault("Content-Type", "application/json")
        request = Request(url, data=body, headers=merged_headers, method="POST")
        return json.loads(self._request_text(request, url))

    def _merge_headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        merged = dict(self.default_headers)
        if headers:
            merged.update(headers)
        return merged

    def _open(self, request: Request):
        opener = build_opener(ProxyHandler({}))
        return opener.open(request, timeout=self.timeout_seconds)

    def _request_text(self, request: Request, url: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self._open(request) as response:
                    return response.read().decode("utf-8")
            except HTTPError as exc:  # pragma: no cover - exercised by integration runs
                response_body = _read_http_error_body(exc)
                last_exc = self._build_http_error(request.get_method(), url, exc, response_body)
                if attempt >= self.max_attempts or not self._should_retry(exc, response_body):
                    raise last_exc from exc
                time.sleep(self._retry_delay(exc, attempt))
            except Exception as exc:  # pragma: no cover - exercised by integration runs
                last_exc = exc
                if attempt >= self.max_attempts or not self._should_retry(exc):
                    raise HttpError(f"{request.get_method()} {url} failed: {exc}") from exc
                time.sleep(self._retry_delay(exc, attempt))
        raise HttpError(f"{request.get_method()} {url} failed: {last_exc}")

    def _should_retry(self, exc: Exception, response_body: str | None = None) -> bool:
        if isinstance(exc, HTTPError):
            if exc.code == 429 and _extract_api_error(response_body).get("error_code") == "insufficient_quota":
                return False
            return exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
        if isinstance(exc, URLError):
            reason = exc.reason
            if isinstance(reason, ssl.SSLError | TimeoutError | OSError):
                return True
            return "timed out" in str(reason).lower()
        return isinstance(exc, ssl.SSLError | TimeoutError)

    def _retry_delay(self, exc: Exception, attempt: int) -> float:
        if isinstance(exc, HTTPError):
            retry_after = exc.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(float(retry_after), 0.0)
                except ValueError:
                    pass
        return self.backoff_seconds * (2 ** (attempt - 1))

    @staticmethod
    def _build_url(url: str, params: dict[str, Any] | None) -> str:
        if not params:
            return url
        clean_params = {key: value for key, value in params.items() if value is not None}
        return f"{url}?{urlencode(clean_params, doseq=True)}"

    def _build_http_error(self, method: str, url: str, exc: HTTPError, response_body: str) -> HttpError:
        api_error = _extract_api_error(response_body)
        details: list[str] = [f"HTTP {exc.code}"]
        if api_error.get("error_code"):
            details.append(str(api_error["error_code"]))
        if api_error.get("message"):
            details.append(str(api_error["message"]))
        elif exc.reason:
            details.append(str(exc.reason))
        return HttpError(
            f"{method} {url} failed: {' - '.join(details)}",
            status_code=exc.code,
            error_type=str(api_error.get("error_type") or "") or None,
            error_code=str(api_error.get("error_code") or "") or None,
            response_body=response_body or None,
        )


def _read_http_error_body(exc: HTTPError) -> str:
    try:
        body = exc.read()
    except Exception:
        return ""
    return body.decode("utf-8", errors="replace")


def _extract_api_error(response_body: str | None) -> dict[str, str]:
    if not response_body:
        return {}
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return {}
    error = payload.get("error")
    if not isinstance(error, dict):
        return {}
    result: dict[str, str] = {}
    for source_key, target_key in (("message", "message"), ("type", "error_type"), ("code", "error_code")):
        value = error.get(source_key)
        if isinstance(value, str) and value.strip():
            result[target_key] = value.strip()
    return result
