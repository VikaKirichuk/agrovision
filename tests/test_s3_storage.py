"""
Модульні тести для s3_storage.py.
Всі виклики boto3 замоковані — реального з'єднання з AWS немає.
"""
import pytest
import sys, os
from unittest.mock import MagicMock, patch, call


# ──────────────────────────────────────────
#  Чистий імпорт s3_storage
# ──────────────────────────────────────────

def _clean_import_s3():
    """
    Видаляє кешований (можливо замокований) модуль s3_storage із sys.modules
    і повертає свіжий імпорт із замоканим boto3/botocore.
    """
    # Видаляємо старі записи
    for key in list(sys.modules.keys()):
        if key in ('s3_storage', 'boto3', 'botocore', 'botocore.exceptions'):
            del sys.modules[key]

    # Мокуємо boto3 і botocore.exceptions
    mock_boto3 = MagicMock()
    mock_botocore = MagicMock()

    # ClientError потрібен як реальний клас для isinstance/except
    class FakeClientError(Exception):
        def __init__(self, error_response=None, operation_name=None):
            self.response = error_response or {}
            super().__init__(str(error_response))

    mock_botocore_exceptions = MagicMock()
    mock_botocore_exceptions.ClientError = FakeClientError

    sys.modules['boto3'] = mock_boto3
    sys.modules['botocore'] = mock_botocore
    sys.modules['botocore.exceptions'] = mock_botocore_exceptions

    backend_path = os.path.join(os.path.dirname(__file__), '..', 'backend')
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    import s3_storage as s3m
    # Патчимо ClientError всередині модуля на наш FakeClientError
    s3m.ClientError = FakeClientError
    return s3m, FakeClientError


# ──────────────────────────────────────────
#  Фікстури
# ──────────────────────────────────────────

@pytest.fixture
def s3_module():
    """Повертає чистий модуль s3_storage із замоканим s3-клієнтом."""
    s3m, FakeClientError = _clean_import_s3()
    mock_client = MagicMock()
    s3m.s3 = mock_client
    return s3m, mock_client, FakeClientError


# ──────────────────────────────────────────
#  13. upload_image
# ──────────────────────────────────────────

class TestUploadImage:

    def test_returns_string_key(self, s3_module, tmp_path):
        """upload_image повертає рядок."""
        s3m, mock_client, _ = s3_module
        f = tmp_path / "field.jpg"
        f.write_bytes(b"fake image data")
        key = s3m.upload_image(str(f), "field.jpg")
        assert isinstance(key, str)

    def test_key_starts_with_uploads_prefix(self, s3_module, tmp_path):
        """Ключ починається з 'uploads/'."""
        s3m, mock_client, _ = s3_module
        f = tmp_path / "field.png"
        f.write_bytes(b"data")
        key = s3m.upload_image(str(f), "field.png")
        assert key.startswith("uploads/")

    def test_key_preserves_extension(self, s3_module, tmp_path):
        """Ключ зберігає розширення файлу."""
        s3m, mock_client, _ = s3_module
        for ext in [".jpg", ".png", ".tiff", ".webp"]:
            f = tmp_path / f"img{ext}"
            f.write_bytes(b"data")
            key = s3m.upload_image(str(f), f"img{ext}")
            assert key.endswith(ext)

    def test_unique_keys_for_same_file(self, s3_module, tmp_path):
        """UUID забезпечує унікальність ключів для одного файлу."""
        s3m, mock_client, _ = s3_module
        f = tmp_path / "same.jpg"
        f.write_bytes(b"data")
        k1 = s3m.upload_image(str(f), "same.jpg")
        k2 = s3m.upload_image(str(f), "same.jpg")
        assert k1 != k2, "UUID забезпечує унікальність ключів"

    def test_upload_file_called_once(self, s3_module, tmp_path):
        """boto3 upload_file викликається рівно один раз."""
        s3m, mock_client, _ = s3_module
        f = tmp_path / "x.jpg"
        f.write_bytes(b"data")
        s3m.upload_image(str(f), "x.jpg")
        mock_client.upload_file.assert_called_once()


# ──────────────────────────────────────────
#  14. get_presigned_url
# ──────────────────────────────────────────

class TestGetPresignedUrl:

    def test_returns_url_on_success(self, s3_module):
        """При успішному виклику повертається URL-рядок."""
        s3m, mock_client, _ = s3_module
        mock_client.generate_presigned_url.return_value = "https://s3.example.com/key?sig=abc"
        url = s3m.get_presigned_url("uploads/abc.jpg")
        assert url.startswith("https://")

    def test_returns_empty_string_on_client_error(self, s3_module):
        """При ClientError функція повертає порожній рядок (не піднімає виняток)."""
        s3m, mock_client, FakeClientError = s3_module
        mock_client.generate_presigned_url.side_effect = FakeClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GeneratePresignedUrl"
        )
        url = s3m.get_presigned_url("uploads/missing.jpg")
        assert url == ""

    def test_default_expiry_is_3600(self, s3_module):
        """За замовчуванням ExpiresIn = 3600 секунд."""
        s3m, mock_client, _ = s3_module
        mock_client.generate_presigned_url.return_value = "https://fake.url"
        s3m.get_presigned_url("uploads/x.jpg")
        _, kwargs = mock_client.generate_presigned_url.call_args
        assert kwargs.get("ExpiresIn") == 3600


# ──────────────────────────────────────────
#  15. delete_image
# ──────────────────────────────────────────

class TestDeleteImage:

    def test_delete_calls_s3(self, s3_module):
        """delete_image викликає delete_object на S3-клієнті."""
        s3m, mock_client, _ = s3_module
        s3m.delete_image("uploads/abc.jpg")
        mock_client.delete_object.assert_called_once()

    def test_delete_silently_handles_client_error(self, s3_module):
        """ClientError при видаленні не піднімає виняток назовні."""
        s3m, mock_client, FakeClientError = s3_module
        mock_client.delete_object.side_effect = FakeClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "gone"}}, "DeleteObject"
        )
        # Не повинно піднімати exception
        s3m.delete_image("uploads/gone.jpg")


# ──────────────────────────────────────────
#  16. _content_type helper
# ──────────────────────────────────────────

class TestContentType:

    @pytest.mark.parametrize("ext,expected", [
        (".jpg",  "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".png",  "image/png"),
        (".tiff", "image/tiff"),
        (".tif",  "image/tiff"),
        (".webp", "image/webp"),
        (".bmp",  "application/octet-stream"),
        ("",      "application/octet-stream"),
    ])
    def test_content_type_mapping(self, s3_module, ext, expected):
        """Розширення коректно маппиться на MIME-тип."""
        s3m, _, _ = s3_module
        assert s3m._content_type(ext) == expected

    def test_uppercase_ext_handled(self, s3_module):
        """Великі літери в розширенні обробляються коректно."""
        s3m, _, _ = s3_module
        assert s3m._content_type(".JPG") == "image/jpeg"
        assert s3m._content_type(".PNG") == "image/png"