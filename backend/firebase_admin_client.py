import json
import os
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore

_APP: Optional[firebase_admin.App] = None
_FIRESTORE: Optional[firestore.Client] = None


def _init_app() -> firebase_admin.App:
    global _APP
    if _APP:
        return _APP

    credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH")

    if credentials_json:
        cred = credentials.Certificate(json.loads(credentials_json))
    elif credentials_path:
        cred = credentials.Certificate(credentials_path)
    else:
        raise RuntimeError(
            "Firebase credentials not configured. Set FIREBASE_CREDENTIALS_JSON "
            "or FIREBASE_CREDENTIALS_PATH."
        )

    _APP = firebase_admin.initialize_app(cred)
    return _APP


def get_firestore_client() -> firestore.Client:
    global _FIRESTORE
    if _FIRESTORE:
        return _FIRESTORE

    _init_app()
    _FIRESTORE = firestore.client()
    return _FIRESTORE
