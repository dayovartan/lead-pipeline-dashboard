def test_health(client):
    assert client.get("/api/healthz").json() == {"ok": True}


def test_me_dev_user(client):
    r = client.get("/api/me").json()
    assert r["is_editor"] is True


def test_no_dbot_dsn():
    """LEADS_PLAN 18: the app has no DSN to dbot-db at all."""
    from app.config import Settings

    assert not any("dbot" in f and "db" in f and f != "db_user" for f in Settings.model_fields)
