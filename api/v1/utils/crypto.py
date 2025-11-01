from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from api.v1.config import auth_config


def _get_fernet() -> Fernet:
    key: Optional[str] = auth_config.FERNET_SECRET_KEY
    if not key:
        raise RuntimeError("FERNET_SECRET_KEY is not configured")
    return Fernet(key)


def fernet_encrypt(text: str) -> str:
    f = _get_fernet()
    return f.encrypt(text.encode("utf-8")).decode("utf-8")


def fernet_decrypt(token: str) -> str:
    try:
        f = _get_fernet()
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Invalid encrypted token") from e
