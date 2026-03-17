from __future__ import annotations

import io
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request

from autopapers.http import HttpClient, HttpError


class StubResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "StubResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class StubHttpClient(HttpClient):
    def __init__(self, results: list[object], **kwargs) -> None:
        super().__init__(**kwargs)
        self.results = list(results)

    def _open(self, request: Request):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class HttpClientTests(unittest.TestCase):
    def test_get_text_retries_http_429_then_succeeds(self) -> None:
        client = StubHttpClient(
            [
                HTTPError(
                    url="https://example.com",
                    code=429,
                    msg="Too Many Requests",
                    hdrs={"Retry-After": "0"},
                    fp=io.BytesIO(b""),
                ),
                StubResponse('{"ok": true}'),
            ],
            max_attempts=3,
            backoff_seconds=0.01,
        )

        with mock.patch("autopapers.http.time.sleep") as sleep_mock:
            body = client.get_text("https://example.com")

        self.assertEqual(body, '{"ok": true}')
        self.assertEqual(len(client.results), 0)
        sleep_mock.assert_called_once_with(0.0)

    def test_get_text_raises_after_retry_budget_is_exhausted(self) -> None:
        client = StubHttpClient(
            [
                HTTPError(
                    url="https://example.com",
                    code=429,
                    msg="Too Many Requests",
                    hdrs={"Retry-After": "0"},
                    fp=io.BytesIO(b""),
                ),
                HTTPError(
                    url="https://example.com",
                    code=429,
                    msg="Too Many Requests",
                    hdrs={"Retry-After": "0"},
                    fp=io.BytesIO(b""),
                ),
            ],
            max_attempts=2,
            backoff_seconds=0.01,
        )

        with mock.patch("autopapers.http.time.sleep"):
            with self.assertRaises(HttpError):
                client.get_text("https://example.com")

    def test_get_text_does_not_retry_insufficient_quota(self) -> None:
        client = StubHttpClient(
            [
                HTTPError(
                    url="https://example.com",
                    code=429,
                    msg="Too Many Requests",
                    hdrs={"Retry-After": "0"},
                    fp=io.BytesIO(
                        (
                            '{"error":{"message":"You exceeded your current quota.","type":"insufficient_quota",'
                            '"code":"insufficient_quota"}}'
                        ).encode("utf-8")
                    ),
                ),
                StubResponse('{"ok": true}'),
            ],
            max_attempts=3,
            backoff_seconds=0.01,
        )

        with mock.patch("autopapers.http.time.sleep") as sleep_mock:
            with self.assertRaises(HttpError) as ctx:
                client.get_text("https://example.com")

        self.assertEqual(ctx.exception.error_code, "insufficient_quota")
        self.assertEqual(len(client.results), 1)
        sleep_mock.assert_not_called()
