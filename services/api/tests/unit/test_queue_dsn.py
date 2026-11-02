from app.core.queue import redis_settings_for


def test_password_is_percent_decoded() -> None:
    # render-env.sh writes the password URL-encoded; Redis must receive the raw value.
    settings = redis_settings_for("redis://:p%40ss%2Fw%3Ard@127.0.0.1:6379/0")
    assert settings.password == "p@ss/w:rd"
    assert settings.host == "127.0.0.1"
    assert settings.database == 0
