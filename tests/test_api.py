"""
Інтеграційні тести для FastAPI (main.py).
Використовує TestClient із замоканими БД та S3 — реального зовнішнього з'єднання немає.
Зовнішні залежності (PostgreSQL, S3, ML-модель) підмінені через dependency_overrides та mock.
"""
import pytest
import sys, os, io
from unittest.mock import MagicMock, patch
from datetime import datetime

# ── Підготовка sys.path та stub-модулів ────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

for mod in ('database', 'models_db', 's3_storage', 'model',
            'boto3', 'sqlalchemy', 'sqlalchemy.orm', 'dotenv'):
    sys.modules.setdefault(mod, MagicMock())

from fastapi.testclient import TestClient  # noqa: E402

# ── Ініціалізація FastAPI-застосунку один раз для всього модуля ────────────
with patch('main.models.Base.metadata.create_all'):
    from main import app, get_current_user, get_db  # noqa: E402


# ──────────────────────────────────────────
#  Фікстури
# ──────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def regular_user():
    """Звичайний активний користувач (не адмін)."""
    u = MagicMock()
    u.id = 1
    u.name = "Тест Юзер"
    u.email = "test@agro.com"
    u.company = "ФГ Агро"
    u.phone = "+380681234567"
    u.is_admin = False
    u.is_active = True
    u.created_at = datetime(2025, 1, 1)
    u.last_login = None
    u.analyses = []
    return u


@pytest.fixture
def admin_user():
    """Адміністратор."""
    u = MagicMock()
    u.id = 99
    u.name = "Адмін"
    u.email = "admin@agro.com"
    u.is_admin = True
    u.is_active = True
    u.created_at = datetime(2025, 1, 1)
    u.last_login = None
    u.analyses = []
    return u


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture(autouse=True)
def clear_overrides():
    """Після кожного тесту скидаємо dependency_overrides."""
    yield
    app.dependency_overrides.clear()


# ──────────────────────────────────────────
#  9. Health-check
# ──────────────────────────────────────────

class TestHealthEndpoint:
    """Базова перевірка доступності сервісу."""

    def test_health_returns_200(self, client):
        """GET /health повертає HTTP 200."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_status_ok(self, client):
        """Тіло відповіді: {"status": "ok"}."""
        resp = client.get("/health")
        assert resp.json() == {"status": "ok"}

    def test_health_no_auth_required(self, client):
        """Ендпоінт доступний без токена — не 401."""
        resp = client.get("/health")
        assert resp.status_code != 401


# ──────────────────────────────────────────
#  10. Реєстрація — POST /register
# ──────────────────────────────────────────

class TestRegisterEndpoint:
    """Перевірка валідації вхідних даних при реєстрації."""

    VALID_PAYLOAD = {
        "name": "Іван Петренко",
        "email": "ivan@farm.com",
        "password": "Pass123",
    }

    def test_register_rejects_invalid_email(self, client):
        """Email без @ — 422 Unprocessable Entity."""
        resp = client.post("/register", json={**self.VALID_PAYLOAD, "email": "not-an-email"})
        assert resp.status_code == 422

    def test_register_rejects_short_password(self, client):
        """Пароль менше 6 символів — 422."""
        resp = client.post("/register", json={**self.VALID_PAYLOAD, "password": "123"})
        assert resp.status_code == 422

    def test_register_rejects_invalid_phone(self, client):
        """Невірний формат телефону — 422."""
        resp = client.post("/register", json={**self.VALID_PAYLOAD, "phone": "12345"})
        assert resp.status_code == 422

    def test_register_rejects_short_name(self, client):
        """Ім'я з одного символу — 422."""
        resp = client.post("/register", json={**self.VALID_PAYLOAD, "name": "А"})
        assert resp.status_code == 422

    def test_register_rejects_missing_name(self, client):
        """Відсутнє обов'язкове поле name — 422."""
        resp = client.post("/register", json={"email": "ivan@farm.com", "password": "Pass123"})
        assert resp.status_code == 422

    def test_register_rejects_missing_email(self, client):
        """Відсутнє обов'язкове поле email — 422."""
        resp = client.post("/register", json={"name": "Іван", "password": "Pass123"})
        assert resp.status_code == 422

    def test_register_schema_accepts_valid_payload_structure(self, client, mock_db):
        """Pydantic пропускає коректний JSON — відповідь не 422 (not Unprocessable)."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = client.post("/register", json=self.VALID_PAYLOAD)
        # 422 означає помилку валідації схеми — з валідними даними не очікується
        assert resp.status_code != 422

    def test_register_duplicate_email_returns_400(self, client, mock_db):
        """Якщо email вже є в БД — 400 Bad Request."""
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = client.post("/register", json=self.VALID_PAYLOAD)
        assert resp.status_code == 400

    def test_register_duplicate_email_error_message(self, client, mock_db):
        """Повідомлення про дублікат містить слово 'email'."""
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = client.post("/register", json=self.VALID_PAYLOAD)
        assert "email" in resp.json()["detail"].lower()


# ──────────────────────────────────────────
#  11. Аналіз поля — POST /analyze
# ──────────────────────────────────────────

class TestAnalyzeEndpoint:
    """Перевірка захисту та валідації ендпоінту аналізу."""

    def test_analyze_without_token_returns_401(self, client):
        """Запит без Authorization-заголовку — 401."""
        resp = client.post(
            "/analyze",
            files={"file": ("test.png", io.BytesIO(b"fake"), "image/png")},
        )
        assert resp.status_code == 401

    def test_analyze_no_file_returns_422(self, client):
        """Запит без файлу — помилка клієнта (401 або 422)."""
        resp = client.post("/analyze")
        assert resp.status_code in (401, 422)
    def test_analyze_pdf_returns_400(self, client, regular_user, mock_db):
        """PDF-файл замість зображення — 400 Bad Request."""
        app.dependency_overrides[get_current_user] = lambda: regular_user
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = client.post(
            "/analyze",
            files={"file": ("doc.pdf", io.BytesIO(b"fake"), "application/pdf")},
            headers={"Authorization": "Bearer valid_token"},
        )
        assert resp.status_code == 400

    def test_analyze_txt_returns_400(self, client, regular_user, mock_db):
        """Текстовий файл — 400 Bad Request."""
        app.dependency_overrides[get_current_user] = lambda: regular_user
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = client.post(
            "/analyze",
            files={"file": ("notes.txt", io.BytesIO(b"text"), "text/plain")},
            headers={"Authorization": "Bearer valid_token"},
        )
        assert resp.status_code == 400

    def test_analyze_pdf_error_message(self, client, regular_user, mock_db):
        """Повідомлення про помилку згадує допустимі формати."""
        app.dependency_overrides[get_current_user] = lambda: regular_user
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = client.post(
            "/analyze",
            files={"file": ("doc.pdf", io.BytesIO(b"fake"), "application/pdf")},
            headers={"Authorization": "Bearer valid_token"},
        )
        detail = resp.json()["detail"].upper()
        assert any(fmt in detail for fmt in ["JPG", "PNG", "TIFF", "WEBP"])


# ──────────────────────────────────────────
#  12. Захист адмін-маршрутів
# ──────────────────────────────────────────

class TestAdminProtection:
    """Адмін-ендпоінти мають бути недоступні без авторизації або для звичайних юзерів."""

    # ── GET /admin/users ──────────────────

    def test_admin_users_no_token_returns_401(self, client):
        resp = client.get("/admin/users")
        assert resp.status_code == 401

    def test_admin_users_regular_user_returns_403(self, client, regular_user):
        """Звичайний юзер (is_admin=False) отримує 403."""
        app.dependency_overrides[get_current_user] = lambda: regular_user
        resp = client.get("/admin/users", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 403

    # ── GET /admin/analyses ───────────────

    def test_admin_analyses_no_token_returns_401(self, client):
        resp = client.get("/admin/analyses")
        assert resp.status_code == 401

    def test_admin_analyses_regular_user_returns_403(self, client, regular_user):
        app.dependency_overrides[get_current_user] = lambda: regular_user
        resp = client.get("/admin/analyses", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 403

    # ── DELETE /admin/users/{id} ──────────

    def test_delete_user_no_token_returns_401(self, client):
        resp = client.delete("/admin/users/2")
        assert resp.status_code == 401

    def test_delete_user_regular_user_returns_403(self, client, regular_user):
        app.dependency_overrides[get_current_user] = lambda: regular_user
        resp = client.delete("/admin/users/2", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 403

    # ── PATCH /admin/users/{id}/toggle-active ──

    def test_toggle_user_no_token_returns_401(self, client):
        resp = client.patch("/admin/users/2/toggle-active")
        assert resp.status_code == 401

    def test_toggle_user_regular_user_returns_403(self, client, regular_user):
        app.dependency_overrides[get_current_user] = lambda: regular_user
        resp = client.patch("/admin/users/2/toggle-active",
                            headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 403

    # ── DELETE /admin/analyses/{id} ───────

    def test_delete_analysis_no_token_returns_401(self, client):
        resp = client.delete("/admin/analyses/5")
        assert resp.status_code == 401

    def test_delete_analysis_regular_user_returns_403(self, client, regular_user):
        app.dependency_overrides[get_current_user] = lambda: regular_user
        resp = client.delete("/admin/analyses/5",
                             headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 403


# ──────────────────────────────────────────
#  13. GET /history — особиста історія
# ──────────────────────────────────────────

class TestHistoryEndpoint:
    """Ендпоінт /history доступний лише авторизованим."""

    def _make_mock_analysis(self):
        """Мок-аналіз із коректним result_json."""
        from unittest.mock import MagicMock
        from datetime import datetime
        a = MagicMock()
        a.id = 1
        a.original_filename = "test.png"
        a.created_at = datetime(2026, 5, 23, 12, 0)
        a.anomalies_count = 0
        a.threshold = "0.4"
        a.image_filename = "uploads/test.png"
        a.result_json = "[]"   # <-- валідний порожній список
        a.user = None
        return a

    def test_history_no_token_returns_401(self, client):
        resp = client.get("/history")
        assert resp.status_code == 401

    def test_history_returns_200_for_authed_user(self, client, regular_user, mock_db):
        """Авторизований юзер отримує 200."""
        mock_db.query.return_value \
            .filter.return_value \
            .order_by.return_value \
            .all.return_value = []
        app.dependency_overrides[get_current_user] = lambda: regular_user
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = client.get("/history", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200

    def test_history_returns_list(self, client, regular_user, mock_db):
        """Відповідь — список (може бути порожнім)."""
        mock_db.query.return_value \
            .filter.return_value \
            .order_by.return_value \
            .all.return_value = []
        app.dependency_overrides[get_current_user] = lambda: regular_user
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = client.get("/history", headers={"Authorization": "Bearer tok"})
        assert isinstance(resp.json(), list)

    def test_history_item_has_detections_field(self, client, regular_user, mock_db):
        """Кожен запис містить поле detections."""
        mock_db.query.return_value \
            .filter.return_value \
            .order_by.return_value \
            .all.return_value = [self._make_mock_analysis()]
        app.dependency_overrides[get_current_user] = lambda: regular_user
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch('main.get_presigned_url', return_value="https://fake.url"):
            resp = client.get("/history", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "detections" in data[0]
        assert isinstance(data[0]["detections"], list)

# ──────────────────────────────────────────
#  14. GET /me
# ──────────────────────────────────────────

class TestMeEndpoint:
    """Ендпоінт /me повертає дані поточного юзера."""

    def test_me_no_token_returns_401(self, client):
        resp = client.get("/me")
        assert resp.status_code == 401

    def test_me_returns_200(self, client, regular_user):
        app.dependency_overrides[get_current_user] = lambda: regular_user
        resp = client.get("/me", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200

    def test_me_contains_email(self, client, regular_user):
        """Відповідь містить email поточного юзера."""
        app.dependency_overrides[get_current_user] = lambda: regular_user
        resp = client.get("/me", headers={"Authorization": "Bearer tok"})
        assert resp.json()["email"] == regular_user.email

    def test_me_contains_name(self, client, regular_user):
        """Відповідь містить name поточного юзера."""
        app.dependency_overrides[get_current_user] = lambda: regular_user
        resp = client.get("/me", headers={"Authorization": "Bearer tok"})
        assert resp.json()["name"] == regular_user.name

    def test_me_is_admin_false_for_regular_user(self, client, regular_user):
        """is_admin = False для звичайного юзера."""
        app.dependency_overrides[get_current_user] = lambda: regular_user
        resp = client.get("/me", headers={"Authorization": "Bearer tok"})
        assert resp.json()["is_admin"] is False

    def test_me_is_admin_true_for_admin(self, client, admin_user):
        """is_admin = True для адміна."""
        app.dependency_overrides[get_current_user] = lambda: admin_user
        resp = client.get("/me", headers={"Authorization": "Bearer tok"})
        assert resp.json()["is_admin"] is True