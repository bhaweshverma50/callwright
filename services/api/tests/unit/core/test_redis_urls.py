"""Redis URLs: TLS (rediss://) reaches both the app client and the arq pool settings."""

from __future__ import annotations

from redis.asyncio.connection import Connection, SSLConnection

from app.core.queue import redis_settings_for
from app.main import build_redis
from tests.conftest import make_settings

TLS = "rediss://default:s3cret@eu1-example.upstash.io:6379/0"


def test_arq_settings_verify_tls_by_default() -> None:
    s = redis_settings_for(TLS)
    assert s.ssl and s.ssl_cert_reqs == "required" and s.ssl_check_hostname
    assert (s.host, s.port, s.username, s.password, s.database) == (
        "eu1-example.upstash.io",
        6379,
        "default",
        "s3cret",
        0,
    )


def test_arq_settings_can_skip_verification_for_test_servers() -> None:
    s = redis_settings_for(TLS + "?ssl_cert_reqs=none")
    assert s.ssl and s.ssl_cert_reqs == "none" and not s.ssl_check_hostname


def test_plain_redis_and_fail_fast_settings() -> None:
    s = redis_settings_for("redis://:pw@10.160.0.2:6379/0", conn_timeout=2, conn_retries=1)
    assert not s.ssl and s.password == "pw"
    assert (s.conn_timeout, s.conn_retries) == (2, 1)


def test_app_client_uses_tls_and_short_timeouts() -> None:
    tls = build_redis(make_settings(redis_url=TLS))
    assert tls.connection_pool.connection_class is SSLConnection
    plain = build_redis(make_settings(redis_url="redis://localhost:56379/14", redis_connect_timeout_s=1.5))
    assert plain.connection_pool.connection_class is Connection
    assert plain.connection_pool.connection_kwargs["socket_connect_timeout"] == 1.5
