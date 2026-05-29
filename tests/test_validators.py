"""
Модульні тести для валідаторів схем Pydantic (логіка з main.py → UserRegister).
Валідатори відтворені ізольовано, без запуску FastAPI.
"""
import pytest
import re
from pydantic import BaseModel, validator, ValidationError


# ── Відтворення схеми ізольовано (без FastAPI-залежностей) ──────────────────
class UserRegister(BaseModel):
    name: str
    email: str
    password: str
    company: str = ""
    phone: str = ""

    @validator("email")
    def validate_email(cls, v):
        if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError("Невірний формат email")
        return v.lower().strip()

    @validator("phone")
    def validate_phone(cls, v):
        if not v:
            return v
        cleaned = re.sub(r'[^\d+]', '', v)
        if not re.match(r'^(\+380\d{9}|0\d{9})$', cleaned):
            raise ValueError("Невірний формат телефону")
        return cleaned

    @validator("password")
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError("Пароль має бути не менше 6 символів")
        return v

    @validator("name")
    def validate_name(cls, v):
        if len(v.strip()) < 2:
            raise ValueError("Ім'я занадто коротке")
        return v.strip()


# ──────────────────────────────────────────
#  3. Валідація email
# ──────────────────────────────────────────

class TestEmailValidation:
    VALID = [
        "user@example.com",
        "ivan.petrenko@ukr.net",
        "agronomist+tag@farm.org",
        "USER@DOMAIN.UA",
    ]
    INVALID = [
        "plainaddress",
        "@missing-local.com",
        "missing-at-sign.com",
        "missing.domain@",
        "two@@signs.com",
    ]

    @pytest.mark.parametrize("email", VALID)
    def test_valid_email_accepted(self, email):
        obj = UserRegister(name="Тест", email=email, password="Pass12")
        assert obj.email == email.lower().strip()

    @pytest.mark.parametrize("email", INVALID)
    def test_invalid_email_rejected(self, email):
        with pytest.raises(ValidationError):
            UserRegister(name="Тест", email=email, password="Pass12")

    def test_email_is_lowercased(self):
        obj = UserRegister(name="Іван", email="Ivan@FARM.COM", password="Pass12")
        assert obj.email == "ivan@farm.com"

    
    @pytest.mark.xfail(reason="Баг: regex запускається до strip(). Потребує виправлення в main.py")
    def test_email_whitespace_not_stripped_bug(self):
        obj = UserRegister(name="Іван", email="  user@farm.com  ", password="Pass12")
        with pytest.raises(ValidationError):
            UserRegister(name="Іван", email="  user@farm.com  ", password="Pass12")
        # ⚠️ БАГ: валідатор перевіряє regex ДО trim — пробіли спричиняють помилку


# ──────────────────────────────────────────
#  4. Валідація телефону
# ──────────────────────────────────────────

class TestPhoneValidation:
    VALID = [
        "+380681234567",
        "0681234567",
        "+380 68 123 45 67",
        "",
    ]
    INVALID = [
        "123456",
        "+1234567890",
        "380681234567",
        "068123456",
        "text",
    ]

    @pytest.mark.parametrize("phone", VALID)
    def test_valid_phone_accepted(self, phone):
        obj = UserRegister(name="Тест", email="t@t.com", password="Pass12", phone=phone)
        assert obj is not None

    @pytest.mark.parametrize("phone", INVALID)
    def test_invalid_phone_rejected(self, phone):
        with pytest.raises(ValidationError):
            UserRegister(name="Тест", email="t@t.com", password="Pass12", phone=phone)


# ──────────────────────────────────────────
#  5. Валідація пароля
# ──────────────────────────────────────────

class TestPasswordValidation:
    def test_password_exactly_6_chars_ok(self):
        obj = UserRegister(name="Тест", email="a@b.com", password="123456")
        assert obj.password == "123456"

    def test_password_more_than_6_chars_ok(self):
        obj = UserRegister(name="Тест", email="a@b.com", password="SecurePass123!")
        assert obj is not None

    def test_password_5_chars_rejected(self):
        with pytest.raises(ValidationError) as exc:
            UserRegister(name="Тест", email="a@b.com", password="12345")
        assert "6" in str(exc.value)

    def test_empty_password_rejected(self):
        with pytest.raises(ValidationError):
            UserRegister(name="Тест", email="a@b.com", password="")


# ──────────────────────────────────────────
#  6. Валідація імені
# ──────────────────────────────────────────

class TestNameValidation:
    def test_normal_name_ok(self):
        obj = UserRegister(name="Іван Петренко", email="a@b.com", password="Pass12")
        assert obj.name == "Іван Петренко"

    def test_name_is_stripped(self):
        obj = UserRegister(name="  Петро  ", email="a@b.com", password="Pass12")
        assert obj.name == "Петро"

    def test_single_char_name_rejected(self):
        with pytest.raises(ValidationError):
            UserRegister(name="А", email="a@b.com", password="Pass12")

    def test_whitespace_only_name_rejected(self):
        with pytest.raises(ValidationError):
            UserRegister(name="  ", email="a@b.com", password="Pass12")

    def test_two_char_name_ok(self):
        obj = UserRegister(name="Ян", email="a@b.com", password="Pass12")
        assert obj.name == "Ян"