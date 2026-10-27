import logging
import os
import threading
import time

import httpx
from celery import shared_task
from django.conf import settings

from paperless.network import PinnedHostHTTPTransport
from paperless.network import validate_outbound_http_url

logger = logging.getLogger("paperless.workflows.webhooks")


# Homelab: OAuth2 client_credentials for webhooks.
#
# A workflow webhook can only send static headers, so it cannot hold an OAuth2 access token that
# expires. When PAPERLESS_WEBHOOK_OAUTH2_URL_PREFIX matches the webhook URL, Paperless asks the
# token endpoint for a short-lived token itself (client_credentials, RFC 6749 §4.4, with the RFC
# 8707 resource) and sends it as `Authorization: Bearer`, replacing any static Authorization
# header. The token is cached in the worker until shortly before it expires; a 401 drops it so
# the next retry asks for a new one. The client secret never leaves the environment.

_OAUTH2_SKEW_SECONDS = 60
_oauth2_lock = threading.Lock()
_oauth2_cache: dict[str, tuple[str, float]] = {}


def _oauth2_config() -> dict[str, str] | None:
    keys = ("URL_PREFIX", "TOKEN_URL", "CLIENT_ID", "CLIENT_SECRET")
    values = {key: os.getenv(f"PAPERLESS_WEBHOOK_OAUTH2_{key}", "").strip() for key in keys}
    if not all(values.values()):
        return None
    values["RESOURCE"] = os.getenv("PAPERLESS_WEBHOOK_OAUTH2_RESOURCE", "").strip()
    values["SCOPE"] = os.getenv("PAPERLESS_WEBHOOK_OAUTH2_SCOPE", "").strip()
    return values


def _oauth2_applies(url: str, config: dict[str, str] | None) -> bool:
    return config is not None and url.startswith(config["URL_PREFIX"])


def _oauth2_token(config: dict[str, str]) -> str:
    key = f"{config['TOKEN_URL']}|{config['CLIENT_ID']}|{config['RESOURCE']}|{config['SCOPE']}"
    with _oauth2_lock:
        cached = _oauth2_cache.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
    form = {"grant_type": "client_credentials"}
    if config["RESOURCE"]:
        form["resource"] = config["RESOURCE"]
    if config["SCOPE"]:
        form["scope"] = config["SCOPE"]
    response = httpx.post(
        config["TOKEN_URL"],
        data=form,
        auth=(config["CLIENT_ID"], config["CLIENT_SECRET"]),
        timeout=10.0,
        follow_redirects=False,
    )
    if response.status_code != 200:
        # The body of a token error carries no secret (RFC 6749 §5.2), only the error code.
        raise httpx.HTTPStatusError(
            f"OAuth2 token request failed with HTTP {response.status_code}",
            request=response.request,
            response=response,
        )
    body = response.json()
    token = body.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("OAuth2 token response without access_token")
    lifetime = body.get("expires_in")
    lifetime = float(lifetime) if isinstance(lifetime, int | float) else 300.0
    with _oauth2_lock:
        _oauth2_cache[key] = (token, time.monotonic() + max(lifetime - _OAUTH2_SKEW_SECONDS, 0.0))
    return token


def _oauth2_forget() -> None:
    with _oauth2_lock:
        _oauth2_cache.clear()


@shared_task(
    retry_backoff=True,
    autoretry_for=(httpx.HTTPStatusError,),
    max_retries=3,
    throws=(httpx.HTTPError,),
)
def send_webhook(
    url: str,
    data: str | dict,
    headers: dict,
    files: dict,
    *,
    as_json: bool = False,
):
    try:
        validate_outbound_http_url(
            url,
            allowed_schemes=settings.WEBHOOKS_ALLOWED_SCHEMES,
            allowed_ports=settings.WEBHOOKS_ALLOWED_PORTS,
            # Internal-address checks happen in transport to preserve ConnectError behavior.
            allow_internal=True,
        )
    except ValueError as e:
        logger.warning("Webhook blocked: %s", e)
        raise

    transport = PinnedHostHTTPTransport(
        allow_internal=settings.WEBHOOKS_ALLOW_INTERNAL_REQUESTS,
    )

    try:
        oauth2 = _oauth2_config()
        uses_oauth2 = _oauth2_applies(url, oauth2)
        send_headers = {
            k: v
            for k, v in (headers or {}).items()
            if k.lower() != "host" and not (uses_oauth2 and k.lower() == "authorization")
        }
        if uses_oauth2:
            send_headers["Authorization"] = f"Bearer {_oauth2_token(oauth2)}"
        post_args = {
            "url": url,
            "headers": send_headers,
            "files": files or None,
        }
        if as_json:
            post_args["json"] = data
        elif isinstance(data, dict):
            post_args["data"] = data
        else:
            post_args["content"] = data

        with httpx.Client(
            transport=transport,
            timeout=5.0,
            follow_redirects=False,
        ) as client:
            response = client.post(
                **post_args,
            )
            if uses_oauth2 and response.status_code == 401:
                _oauth2_forget()
            response.raise_for_status()
            logger.info(
                f"Webhook sent to {url}",
            )
    except Exception as e:
        logger.error(
            f"Failed attempt sending webhook to {url}: {e}",
        )
        raise e
    finally:
        transport.close()
