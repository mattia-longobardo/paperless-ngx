from unittest import mock

import httpx
import pytest

from documents.workflows import webhooks
from documents.workflows.webhooks import send_webhook

PREFIX = "https://ledger.example.test/api/v1/"
URL = f"{PREFIX}imports"


@pytest.fixture
def oauth2_env(monkeypatch):
    monkeypatch.setenv("PAPERLESS_WEBHOOK_OAUTH2_URL_PREFIX", PREFIX)
    monkeypatch.setenv(
        "PAPERLESS_WEBHOOK_OAUTH2_TOKEN_URL",
        "https://ledger.example.test/token",
    )
    monkeypatch.setenv("PAPERLESS_WEBHOOK_OAUTH2_CLIENT_ID", "client")
    monkeypatch.setenv("PAPERLESS_WEBHOOK_OAUTH2_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "PAPERLESS_WEBHOOK_OAUTH2_RESOURCE",
        "https://ledger.example.test/api/v1",
    )
    monkeypatch.setenv("PAPERLESS_WEBHOOK_OAUTH2_SCOPE", "imports")


@pytest.fixture(autouse=True)
def isolated_webhook():
    webhooks._oauth2_forget()
    with (
        mock.patch("documents.workflows.webhooks.validate_outbound_http_url"),
        mock.patch("documents.workflows.webhooks.httpx.post") as token_post,
        mock.patch("documents.workflows.webhooks.httpx.Client") as client,
    ):
        token_post.return_value = httpx.Response(
            200,
            json={"access_token": "short-lived", "expires_in": 3600},
            request=httpx.Request("POST", "https://ledger.example.test/token"),
        )
        post = client.return_value.__enter__.return_value.post
        post.return_value = httpx.Response(
            200,
            request=httpx.Request("POST", URL),
        )
        yield token_post, post
    webhooks._oauth2_forget()


def _send(url: str = URL) -> None:
    send_webhook(
        url=url,
        data="body",
        headers={"Authorization": "Token static", "X-Other": "kept"},
        files={},
    )


@pytest.mark.usefixtures("oauth2_env")
def test_oauth2_token_replaces_static_authorization(isolated_webhook) -> None:
    token_post, post = isolated_webhook

    _send()

    token_post.assert_called_once()
    assert token_post.call_args.kwargs["auth"] == ("client", "secret")
    assert token_post.call_args.kwargs["data"] == {
        "grant_type": "client_credentials",
        "resource": "https://ledger.example.test/api/v1",
        "scope": "imports",
    }
    assert post.call_args.kwargs["headers"] == {
        "X-Other": "kept",
        "Authorization": "Bearer short-lived",
    }


@pytest.mark.usefixtures("oauth2_env")
def test_oauth2_token_is_cached_between_webhooks(isolated_webhook) -> None:
    token_post, _ = isolated_webhook

    _send()
    _send()

    token_post.assert_called_once()


@pytest.mark.usefixtures("oauth2_env")
def test_oauth2_unauthorized_response_drops_cached_token(isolated_webhook) -> None:
    token_post, post = isolated_webhook
    post.return_value = httpx.Response(401, request=httpx.Request("POST", URL))

    with pytest.raises(httpx.HTTPStatusError):
        _send()
    post.return_value = httpx.Response(200, request=httpx.Request("POST", URL))
    _send()

    assert token_post.call_count == 2


@pytest.mark.usefixtures("oauth2_env")
def test_oauth2_ignores_url_outside_prefix(isolated_webhook) -> None:
    token_post, post = isolated_webhook

    _send("https://other.example.test/hook")

    token_post.assert_not_called()
    assert post.call_args.kwargs["headers"]["Authorization"] == "Token static"


def test_oauth2_is_off_without_configuration(isolated_webhook) -> None:
    token_post, post = isolated_webhook

    _send()

    token_post.assert_not_called()
    assert post.call_args.kwargs["headers"]["Authorization"] == "Token static"
