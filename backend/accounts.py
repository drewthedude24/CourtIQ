"""Log in with an email, and log out.

There is no password: typing an email logs you in, and a new email makes a new account.
So anyone who knows your email can log in as you. That's fine for a hobby project, and an
emailed code would fix it later.

A login is a long random token in a cookie. The database keeps only its SHA-256 hash in
`login_sessions`, so logging out (deleting the row) ends it right away, and someone who
reads the table still can't log in as anyone.
"""

import hashlib
import secrets
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import database


COOKIE_NAME = "courtiq_login"
LOGIN_DAYS = 30

router = APIRouter()


class LoginRequest(BaseModel):
    email: str


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(courtiq_login: Annotated[str | None, Cookie()] = None):
    """The logged-in user ({"id", "email"}). Routes that list it as a dependency answer 401
    to a browser that isn't logged in."""
    user = database.get_login_user(hash_token(courtiq_login)) if courtiq_login else None
    if user is None:
        raise HTTPException(status_code=401, detail="Log in first.")
    return user


def start_login(request, response, user_id):
    token = secrets.token_urlsafe(32)
    database.create_login(user_id, hash_token(token), LOGIN_DAYS)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=LOGIN_DAYS * 24 * 60 * 60,  # Stays after the browser closes.
        httponly=True,  # Page scripts can't read it.
        samesite="lax",  # Not sent with a form posted from another site.
        # "https only" when the site is on https. The live site is plain http for now.
        secure=request.url.scheme == "https",
    )


@router.post("/api/login")
def log_in(login: LoginRequest, request: Request, response: Response):
    email = login.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a real email address.")
    start_login(request, response, database.get_or_create_user(email))
    return {"email": email}


@router.post("/api/logout", status_code=204)
def log_out(response: Response, courtiq_login: Annotated[str | None, Cookie()] = None):
    if courtiq_login:
        database.delete_login(hash_token(courtiq_login))
    response.delete_cookie(COOKIE_NAME)


@router.get("/api/me")
def me(user: Annotated[dict, Depends(current_user)]):
    return {"email": user["email"]}
