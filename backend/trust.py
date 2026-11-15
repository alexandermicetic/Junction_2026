"""Cryptographic quote signing and verification."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from dotenv import load_dotenv
from fastapi import HTTPException

# The unrelated PyPI package named ``jwt`` also installs an importable ``jwt``
# module, but it does not provide PyJWT's encode/decode API. Fail at startup with
# a useful hint instead of returning a 500 when the first quote is signed.
if not callable(getattr(jwt, "encode", None)) or not callable(getattr(jwt, "decode", None)):
    raise ImportError(
        "The imported 'jwt' module is not PyJWT. In the Python environment used "
        "to run the backend, run: python -m pip uninstall jwt && "
        "python -m pip install --force-reinstall PyJWT"
    )

load_dotenv(Path(__file__).resolve().parent / ".env")


def _secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET must be configured in backend/.env")
    return secret


def sign_quote(quote_data: dict) -> str:
    """Sign quote contents with HS256 and a 15-minute expiration."""
    now = datetime.now(timezone.utc)
    payload = {**quote_data, "iat": now, "exp": now + timedelta(minutes=15)}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def verify_quote(token: str) -> dict:
    """Verify a quote signature and expiration, returning the trusted claims."""
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=400, detail="The quote token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail="The quote token is invalid or has been tampered with") from exc
