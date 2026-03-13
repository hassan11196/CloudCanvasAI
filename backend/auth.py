from typing import Dict

from fastapi import HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth

from firebase_admin_client import get_firestore_client

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Dict[str, str]:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing auth token")

    try:
        get_firestore_client()
        decoded = firebase_auth.verify_id_token(credentials.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid auth token: {exc}") from exc

    return {
        "uid": decoded.get("uid") or decoded.get("user_id"),
        "email": decoded.get("email", ""),
    }


def get_firestore():
    return get_firestore_client()
