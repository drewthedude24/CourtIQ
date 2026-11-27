"""Sign up, log in and log out.

A login is a long random token in a cookie. The database keeps only its SHA-256 hash in
`login_sessions`, so logging out (deleting the row) ends it right away, and someone who
reads the table still can't log in as anyone. Passwords are kept only as argon2 hashes.
"""

import hashlib
import secrets
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import database


COOKIE_NAME = "courtiq_login"
LOGIN_DAYS = 30
MIN_PASSWORD_LENGTH = 8

password_hasher = PasswordHasher()
router = APIRouter()


class Credentials(BaseModel):
    email: str
    password: str


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


def password_matches(password_hash, password):
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


@router.post("/api/signup", status_code=201)
def sign_up(credentials: Credentials, request: Request, response: Response):
    email = credentials.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a real email address.")
    if len(credentials.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Use a password of at least {MIN_PASSWORD_LENGTH} characters.",
        )
    user_id = database.create_user(email, password_hasher.hash(credentials.password))
    if user_id is None:
        raise HTTPException(status_code=409, detail="That email already has an account. Log in instead.")
    start_login(request, response, user_id)
    return {"email": email}


@router.post("/api/login")
def log_in(credentials: Credentials, request: Request, response: Response):
    user = database.get_user_by_email(credentials.email.strip().lower())
    if user is None or not password_matches(user["password_hash"], credentials.password):
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    start_login(request, response, user["id"])
    return {"email": user["email"]}


@router.post("/api/logout", status_code=204)
def log_out(response: Response, courtiq_login: Annotated[str | None, Cookie()] = None):
    if courtiq_login:
        database.delete_login(hash_token(courtiq_login))
    response.delete_cookie(COOKIE_NAME)


@router.get("/api/me")
def me(user: Annotated[dict, Depends(current_user)]):
    return {"email": user["email"]}
