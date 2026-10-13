"""Shared Groq transport, warmed during capture without uploading any audio."""
from __future__ import annotations

import logging
import os
import threading

import httpx
from groq import Groq

_client = None
_client_lock = threading.Lock()
_warm_lock = threading.Lock()
_logger = logging.getLogger("whisper-dictate")


def get_client() -> Groq:
    global _client
    with _client_lock:
        if _client is None:
            transport = httpx.Client(
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=4,
                                   keepalive_expiry=120),
                timeout=httpx.Timeout(15, connect=5))
            _client = Groq(api_key=os.environ["GROQ_API_KEY"], http_client=transport,
                           max_retries=2, timeout=httpx.Timeout(15, connect=5))
        return _client


def warm_during_capture() -> threading.Event:
    """Return a stop event; only free model-list GETs are sent, never mic data."""
    stop = threading.Event()

    def run():
        if not _warm_lock.acquire(blocking=False):
            return
        try:
            while not stop.is_set():
                try:
                    get_client().with_options(max_retries=0, timeout=5).models.list()
                except Exception as exc:
                    _logger.debug("Groq connection warmup unavailable: %s", type(exc).__name__)
                if stop.wait(30):
                    break
        finally:
            _warm_lock.release()

    threading.Thread(target=run, name="groq-connection-warmup", daemon=True).start()
    return stop
