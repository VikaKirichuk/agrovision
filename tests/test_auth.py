"""
Модульні тести для auth.py
Покриває: хешування паролів, верифікацію, генерацію JWT-токенів.
"""
import pytest
from datetime import timedelta
from unittest.mock import MagicMock, patch
from jose import jwt

# Щоб не потребувати реальної БД — мокуємо залежності
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    SECRET_KEY,
    ALGORITHM,
)


# ──────────────────────────────────────────
#  1. Хешування та верифікація пароля
# ──────────────────────────────────────────

class TestPasswordHashing:
    """Перевірка bcrypt-хешування та верифікації."""

    def test_hash_is_not_plaintext(self):
        """Хеш не повинен збігатися з відкритим паролем."""
        password = "MySecret123"
        hashed = get_password_hash(password)
        assert hashed != password

    def test_hash_starts_with_bcrypt_prefix(self):
        """bcrypt-хеш завжди починається з $2b$."""
        hashed = get_password_hash("test_pass")
        assert hashed.startswith("$2b$")

    def test_same_password_gives_different_hashes(self):
        """Через сіль два хеші одного пароля — різні (salt унікальний)."""
        pw = "SamePassword!"
        h1 = get_password_hash(pw)
        h2 = get_password_hash(pw)
        assert h1 != h2

    def test_verify_correct_password(self):
        """verify_password повертає True для правильного пароля."""
        pw = "CorrectHorseBattery"
        hashed = get_password_hash(pw)
        assert verify_password(pw, hashed) is True

    def test_verify_wrong_password(self):
        """verify_password повертає False для неправильного пароля."""
        hashed = get_password_hash("RealPassword")
        assert verify_password("WrongPassword", hashed) is False

    def test_verify_empty_string_fails(self):
        """Порожній рядок не проходить верифікацію."""
        hashed = get_password_hash("nonempty")
        assert verify_password("", hashed) is False

    def test_verify_with_extra_space_fails(self):
        """Пароль з пробілом на кінці — не збігається."""
        pw = "NoTrailingSpace"
        hashed = get_password_hash(pw)
        assert verify_password(pw + " ", hashed) is False


# ──────────────────────────────────────────
#  2. Генерація JWT-токенів
# ──────────────────────────────────────────

class TestJWTToken:
    """Перевірка генерації та декодування JWT."""

    def test_token_is_string(self):
        """create_access_token повертає рядок."""
        token = create_access_token({"sub": "42"})
        assert isinstance(token, str)

    def test_token_contains_subject(self):
        """Декодований токен містить правильний sub."""
        token = create_access_token({"sub": "99"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "99"

    def test_token_has_expiry(self):
        """Токен містить поле exp."""
        token = create_access_token({"sub": "1"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_custom_expiry_delta(self):
        """Токен із custom delta: exp після поточного часу і не більш ніж delta+10сек."""
        from datetime import datetime
        delta = timedelta(minutes=30)
        before = datetime.utcnow()
        token = create_access_token({"sub": "5"}, expires_delta=delta)
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp_time = datetime.utcfromtimestamp(payload["exp"])
        # exp_time має бути приблизно before + delta (з допуском ±10 сек)
        diff = abs((exp_time - before - delta).total_seconds())
        assert diff < 10, f"Різниця exp занадто велика: {diff}s"

    def test_token_with_wrong_secret_fails(self):
        """Декодування з неправильним SECRET_KEY піднімає JWTError."""
        from jose import JWTError
        token = create_access_token({"sub": "7"})
        with pytest.raises(JWTError):
            jwt.decode(token, "wrong-secret", algorithms=[ALGORITHM])

    def test_extra_fields_preserved(self):
        """Додаткові поля payload зберігаються в токені."""
        token = create_access_token({"sub": "3", "role": "admin"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["role"] == "admin"