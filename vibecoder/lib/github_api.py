# -*- coding: utf-8 -*-
import logging
import random
import time

import requests


def uncap_child_memory():
    """subprocess ``preexec_fn`` that lifts RLIMIT_AS for a spawned child.

    Odoo's prefork HTTP workers call ``resource.setrlimit(RLIMIT_AS, ...)`` on
    themselves (the ``limit_memory_hard`` config option) to bound their own
    memory — but RLIMIT_AS is inherited across fork/exec, so without this every
    child process (npm/vite/node, the Claude CLI) inherits the same address-space
    cap. Node's V8 reserves several GB of virtual address space for its WASM
    heap regardless of actual usage, so it crashes immediately with
    'WebAssembly.instantiate(): Out of memory' under that inherited limit. This
    runs in the forked child before exec, so it only affects the child.
    """
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))

from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BASE_DELAY = 1.0


def gh_request(method, url, token=None, **kw):
    """requests.request wrapper with exponential back-off + jitter retries.

    Retries only on 429/5xx responses and transport-level ConnectionError, up to
    ``MAX_ATTEMPTS`` attempts, honoring GitHub's ``Retry-After`` header when
    present. Raises a clean UserError (never a bare traceback) once retries are
    exhausted, so every call site gets uniform, friendly error handling.
    """
    headers = dict(kw.pop("headers", None) or {})
    headers.setdefault("Accept", "application/vnd.github+json")
    headers.setdefault("X-GitHub-Api-Version", "2022-11-28")
    if token:
        headers["Authorization"] = "Bearer %s" % token
    timeout = kw.pop("timeout", 30)

    last_exc = None
    last_resp = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.request(
                method, url, headers=headers, timeout=timeout, **kw)
        except requests.RequestException as e:
            last_exc = e
            _logger.warning(
                "GitHub API %s %s failed (attempt %s/%s): %s",
                method, url, attempt, MAX_ATTEMPTS, e)
            if attempt < MAX_ATTEMPTS:
                _sleep_backoff(attempt, None)
                continue
            raise UserError(_(
                "Could not reach GitHub after %(n)s attempts: %(err)s",
                n=MAX_ATTEMPTS, err=str(e)))

        if resp.status_code not in RETRYABLE_STATUSES:
            return resp

        last_resp = resp
        _logger.warning(
            "GitHub API %s %s returned %s (attempt %s/%s)",
            method, url, resp.status_code, attempt, MAX_ATTEMPTS)
        if attempt < MAX_ATTEMPTS:
            _sleep_backoff(attempt, resp.headers.get("Retry-After"))
            continue

    if last_resp is not None:
        raise UserError(_(
            "GitHub rejected the request after %(n)s attempts (HTTP %(code)s): "
            "%(body)s", n=MAX_ATTEMPTS, code=last_resp.status_code,
            body=last_resp.text[:300]))
    raise UserError(_("Could not reach GitHub: %(err)s", err=str(last_exc)))


def _sleep_backoff(attempt, retry_after):
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            delay = BASE_DELAY * (2 ** (attempt - 1))
    else:
        delay = BASE_DELAY * (2 ** (attempt - 1))
    delay += random.uniform(0, delay * 0.25)
    time.sleep(min(delay, 20))


def gh_json(method, url, token=None, **kw):
    """Same as gh_request, but raises on non-2xx and returns parsed JSON."""
    resp = gh_request(method, url, token=token, **kw)
    if resp.status_code >= 400:
        _logger.warning("GitHub API %s %s -> %s: %s",
                         method, url, resp.status_code, resp.text[:500])
        raise UserError(_(
            "GitHub API error (HTTP %(code)s): %(body)s",
            code=resp.status_code, body=resp.text[:300]))
    if not resp.content:
        return {}
    return resp.json()
