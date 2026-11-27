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


def sign_up(client, email="ann@example.com", password="correct horse"):
    return client.post("/api/signup", json={"email": email, "password": password})


def test_signing_up_logs_you_in(client):
    response = sign_up(client)

    assert response.status_code == 201
    assert client.get("/api/me").json() == {"email": "ann@example.com"}


def test_login_cookie_is_hidden_from_page_scripts_and_lasts_30_days(client):
    cookie = sign_up(client).headers["set-cookie"]

    assert cookie.startswith("courtiq_login=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=2592000" in cookie
    # The test client talks plain http, like the live site, so the cookie can't be https-only.
    assert "Secure" not in cookie


def test_email_is_saved_trimmed_and_lowercase(client):
    sign_up(client, email="  Ann@Example.COM ")

    assert client.get("/api/me").json() == {"email": "ann@example.com"}


def test_password_is_stored_as_an_argon2_hash(client):
    sign_up(client, password="correct horse")

    with database.connect() as connection:
        stored = connection.execute("SELECT password_hash FROM users").fetchone()["password_hash"]
    assert stored.startswith("$argon2id$")
    assert "correct horse" not in stored


def test_login_token_is_stored_only_as_a_hash(client):
    # Someone who reads the table can't copy a row into a cookie and be logged in.
    sign_up(client)
    token = client.cookies["courtiq_login"]

    with database.connect() as connection:
        stored = connection.execute("SELECT token_hash FROM login_sessions").fetchone()["token_hash"]
    assert stored != token
    assert len(stored) == 64


@pytest.mark.parametrize(
    ("email", "password"),
    [("not-an-email", "correct horse"), ("ann@example.com", "short")],
)
def test_bad_email_or_short_password_is_rejected(client, email, password):
    response = sign_up(client, email=email, password=password)

    assert response.status_code == 400
    assert client.get("/api/me").status_code == 401


def test_an_email_can_only_sign_up_once(client):
    sign_up(client)

    response = sign_up(TestClient(app), email="ANN@example.com")

    assert response.status_code == 409


def test_log_in_with_the_right_password(client):
    sign_up(client)
    other_browser = TestClient(app)

    response = other_browser.post("/api/login", json={"email": "Ann@example.com", "password": "correct horse"})

    assert response.status_code == 200
    assert other_browser.get("/api/me").json() == {"email": "ann@example.com"}


@pytest.mark.parametrize(
    ("email", "password"),
    [("ann@example.com", "wrong horse"), ("nobody@example.com", "correct horse")],
)
def test_wrong_password_or_unknown_email_cannot_log_in(client, email, password):
    sign_up(client)
    other_browser = TestClient(app)

    response = other_browser.post("/api/login", json={"email": email, "password": password})

    assert response.status_code == 401
    # The same answer for both, so nobody can test which emails have accounts by logging in.
    assert response.json()["detail"] == "Wrong email or password."
    assert other_browser.get("/api/me").status_code == 401


def test_log_out_ends_the_login_on_the_server(client):
    sign_up(client)
    token = client.cookies["courtiq_login"]

    assert client.post("/api/logout").status_code == 204

    assert client.get("/api/me").status_code == 401
    # Even a copy of the old cookie no longer works, because its row is gone.
    copied = TestClient(app, cookies={"courtiq_login": token})
    assert copied.get("/api/me").status_code == 401


def test_an_expired_login_no_longer_works(client):
    sign_up(client)
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
        ("get", "/api/stats/fatigue"),
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
