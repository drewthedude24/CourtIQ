import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.app import app


@pytest.fixture(autouse=True)
def empty_database():
    with database.connect() as connection:
        connection.execute("TRUNCATE sessions, shots, users, login_sessions")


@pytest.fixture
def client():
    # A fresh browser each test: its own cookie jar.
    return TestClient(app)


def log_in(client, email="ann@example.com"):
    return client.post("/api/login", json={"email": email})


def users_count():
    with database.connect() as connection:
        return connection.execute("SELECT count(*) AS n FROM users").fetchone()["n"]


def test_typing_an_email_logs_you_in(client):
    response = log_in(client)

    assert response.status_code == 200
    assert response.json() == {"email": "ann@example.com"}
    assert client.get("/api/me").json() == {"email": "ann@example.com"}


def test_login_cookie_is_hidden_from_page_scripts_and_lasts_30_days(client):
    cookie = log_in(client).headers["set-cookie"]

    assert cookie.startswith("courtiq_login=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=2592000" in cookie
    # The test client talks plain http, like the live site, so the cookie can't be https-only.
    assert "Secure" not in cookie


def test_email_is_saved_trimmed_and_lowercase(client):
    log_in(client, email="  Ann@Example.COM ")

    assert client.get("/api/me").json() == {"email": "ann@example.com"}


def test_login_token_is_stored_only_as_a_hash(client):
    # Someone who reads the table can't copy a row into a cookie and be logged in.
    log_in(client)
    token = client.cookies["courtiq_login"]

    with database.connect() as connection:
        stored = connection.execute("SELECT token_hash FROM login_sessions").fetchone()["token_hash"]
    assert stored != token
    assert len(stored) == 64


@pytest.mark.parametrize("email", ["not-an-email", "", "   "])
def test_something_that_is_not_an_email_is_rejected(client, email):
    response = log_in(client, email=email)

    assert response.status_code == 400
    assert client.get("/api/me").status_code == 401
    assert users_count() == 0


def test_a_new_email_makes_a_new_account(client):
    log_in(client, email="ann@example.com")
    log_in(TestClient(app), email="ben@example.com")

    assert users_count() == 2


def test_the_same_email_again_is_the_same_account(client):
    log_in(client)
    other_browser = TestClient(app)

    log_in(other_browser, email="ANN@example.com")

    assert users_count() == 1
    assert other_browser.get("/api/me").json() == {"email": "ann@example.com"}


def test_there_is_no_sign_up_route_any_more(client):
    client.post("/api/signup", json={"email": "ann@example.com"})

    assert client.get("/api/me").status_code == 401


def test_log_out_ends_the_login_on_the_server(client):
    log_in(client)
    token = client.cookies["courtiq_login"]

    assert client.post("/api/logout").status_code == 204

    assert client.get("/api/me").status_code == 401
    # Even a copy of the old cookie no longer works, because its row is gone.
    copied = TestClient(app, cookies={"courtiq_login": token})
    assert copied.get("/api/me").status_code == 401


def test_an_expired_login_no_longer_works(client):
    log_in(client)
    with database.connect() as connection:
        connection.execute("UPDATE login_sessions SET expires_at = now() - interval '1 second'")

    assert client.get("/api/me").status_code == 401


def test_made_up_cookie_is_not_logged_in():
    client = TestClient(app, cookies={"courtiq_login": "made-up"})

    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/sessions"),
        ("get", "/api/stats"),
        ("get", "/api/stats/form"),
        ("get", "/api/sessions/abc"),
        ("delete", "/api/sessions/abc"),
        ("get", "/api/sessions/abc/video"),
        ("get", "/api/sessions/abc/shots/1/form/knee_bend_deg.jpg"),
        ("post", "/api/sessions"),
    ],
)
def test_every_data_route_needs_a_login(client, method, path):
    response = getattr(client, method)(path)

    assert response.status_code == 401


def test_health_check_needs_no_login(client):
    assert client.get("/api/health").status_code == 200
