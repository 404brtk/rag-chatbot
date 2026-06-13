from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models


def _get_fernet():
    keys = settings.FERNET_KEYS
    if isinstance(keys, str):
        keys = [keys]
    return MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])


class EncryptedTextField(models.TextField):
    def get_prep_value(self, value):
        if value is None:
            return None
        value = super().get_prep_value(value)
        return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        try:
            return _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            raise ValueError(f"Failed to decrypt field {self.name}")
