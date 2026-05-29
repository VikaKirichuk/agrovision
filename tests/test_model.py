"""
Модульні тести для model.py (ML-пайплайн).
Покриває: препроцесинг, коректність тензора, формат виводу inference.
Модель не завантажується — використовуємо mock для ізоляції.
"""
import pytest
import numpy as np
import torch
import tempfile, os, base64, sys
from unittest.mock import MagicMock, patch
from PIL import Image


# ──────────────────────────────────────────
#  Допоміжна функція: чистий імпорт model
# ──────────────────────────────────────────

def _clean_import_model():
    """
    Видаляє кешовані копії model/transformers із sys.modules,
    мокує transformers і повертає свіжий модуль model.
    """
    # Видаляємо старі (можливо замокані) записи
    for key in list(sys.modules.keys()):
        if key in ('model', 'transformers') or key.startswith('transformers.'):
            del sys.modules[key]

    # Підміняємо transformers заглушкою
    mock_tr = MagicMock()
    sys.modules['transformers'] = mock_tr

    # Переконуємось, що шлях до backend є в sys.path
    backend_path = os.path.join(os.path.dirname(__file__), '..', 'backend')
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    import model as m
    return m


# ──────────────────────────────────────────
#  Фікстури
# ──────────────────────────────────────────

@pytest.fixture
def rgb_image_path(tmp_path):
    """Тимчасове RGB-зображення 200×200."""
    img = Image.fromarray(
        np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    )
    p = tmp_path / "test_field.png"
    img.save(str(p))
    return str(p)


@pytest.fixture
def small_image_path(tmp_path):
    """Маленьке зображення 32×32 для перевірки масштабування."""
    img = Image.fromarray(
        np.random.randint(0, 255, (32, 32, 3), dtype=np.uint8)
    )
    p = tmp_path / "small.jpg"
    img.save(str(p))
    return str(p)


# ──────────────────────────────────────────
#  7. Препроцесинг
# ──────────────────────────────────────────

class TestPreprocess:
    """Перевірка функції preprocess() з model.py."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Перед кожним тестом чисто імпортуємо model."""
        self.m = _clean_import_model()

    def test_output_is_float_tensor(self, rgb_image_path):
        """Результат preprocess — float32 тензор."""
        tensor = self.m.preprocess(rgb_image_path)
        assert tensor.dtype == torch.float32

    def test_output_shape_is_correct(self, rgb_image_path):
        """Очікуваний shape: (1, 4, 512, 512) — RGB + NIR."""
        tensor = self.m.preprocess(rgb_image_path)
        assert tensor.shape == (1, 4, 512, 512)

    def test_small_image_is_resized(self, small_image_path):
        """Зображення 32×32 масштабується до 512×512."""
        tensor = self.m.preprocess(small_image_path)
        assert tensor.shape[-2:] == (512, 512)

    def test_pixel_values_normalized(self, rgb_image_path):
        """Після нормалізації значення не в діапазоні [0, 1], бо застосовано mean/std."""
        tensor = self.m.preprocess(rgb_image_path)
        has_negative = (tensor < 0).any().item()
        has_above_one = (tensor > 1).any().item()
        assert has_negative or has_above_one, \
            "Нормалізація ImageNet має зрушувати значення за [0,1]"

    def test_no_nan_in_output(self, rgb_image_path):
        """Препроцесинг не повинен давати NaN."""
        tensor = self.m.preprocess(rgb_image_path)
        assert not torch.isnan(tensor).any()

    def test_no_inf_in_output(self, rgb_image_path):
        """Препроцесинг не повинен давати Inf."""
        tensor = self.m.preprocess(rgb_image_path)
        assert not torch.isinf(tensor).any()


# ──────────────────────────────────────────
#  8. Формат виводу run_inference (mock-модель)
# ──────────────────────────────────────────

class TestRunInferenceMocked:
    """
    Перевірка структури виводу run_inference() без реального .pth-файлу.
    Модель підміняється mock-об'єктом, що повертає нульові logits.
    """

    def _setup_mock_model(self, probs_value=0.0):
        m = _clean_import_model()

        # Реальний 4D тензор як повертає smp напряму
        logits = torch.full((1, 8, 128, 128), probs_value)

        mock_model = MagicMock()
        mock_model.return_value = logits  # smp повертає тензор напряму, не об'єкт з .logits

        # Мокаємо load_model щоб повертала наш mock
        m.load_model = lambda: mock_model
        return m
    
    def test_returns_dict_with_required_keys(self, rgb_image_path):
        """Відповідь — словник із ключами detections і mask_base64."""
        m = self._setup_mock_model(0.0)
        result = m.run_inference(rgb_image_path, threshold=0.4)
        assert isinstance(result, dict)
        assert "detections" in result
        assert "mask_base64" in result

    def test_no_detections_when_probs_below_threshold(self, rgb_image_path):
        """Якщо всі ймовірності < поріг — список аномалій порожній.

        Увага: модель застосовує softmax до логітів. Рівномірні логіти (напр. 0.1)
        після softmax дають ~1/8 = 0.125 на клас — нижче порогу 0.2.
        Використовуємо поріг 0.99, щоб гарантовано не пройшов жоден клас.
        """
        m = self._setup_mock_model(0.1)
        result = m.run_inference(rgb_image_path, threshold=0.99)
        assert result["detections"] == []

    def test_detections_present_when_probs_above_threshold(self, rgb_image_path):
        """Якщо ймовірності > поріг — аномалії виявлено."""
        m = self._setup_mock_model(0.9)
        result = m.run_inference(rgb_image_path, threshold=0.4)
        assert len(result["detections"]) > 0

    def test_detection_fields_present(self, rgb_image_path):
        """Кожна аномалія містить обов'язкові поля."""
        m = self._setup_mock_model(0.9)
        result = m.run_inference(rgb_image_path, threshold=0.4)
        required = {"class", "label_ua", "area_pct", "confidence", "advice"}
        for det in result["detections"]:
            assert required.issubset(det.keys()), \
                f"Відсутні поля: {required - det.keys()}"

    def test_mask_base64_is_valid(self, rgb_image_path):
        """mask_base64 декодується без помилок і є PNG."""
        m = self._setup_mock_model(0.9)
        result = m.run_inference(rgb_image_path, threshold=0.4)
        raw = base64.b64decode(result["mask_base64"])
        assert raw[:4] == b'\x89PNG'

    def test_area_pct_within_range(self, rgb_image_path):
        """area_pct — відсоток від 0 до 100."""
        m = self._setup_mock_model(0.9)
        result = m.run_inference(rgb_image_path, threshold=0.4)
        for det in result["detections"]:
            assert 0.0 <= det["area_pct"] <= 100.0

    def test_confidence_within_range(self, rgb_image_path):
        """confidence — значення від 0 до 1."""
        m = self._setup_mock_model(0.9)
        result = m.run_inference(rgb_image_path, threshold=0.4)
        for det in result["detections"]:
            assert 0.0 <= det["confidence"] <= 1.0

    @pytest.mark.parametrize("threshold", [0.2, 0.4, 0.6, 0.8])
    def test_higher_threshold_fewer_detections(self, rgb_image_path, threshold):
        m = _clean_import_model()

        torch.manual_seed(42)
        logits = torch.rand(1, 8, 128, 128)

        mock_model = MagicMock()
        mock_model.return_value = logits
        m.load_model = lambda: mock_model 

        r_low  = m.run_inference(rgb_image_path, threshold=0.2)
        r_high = m.run_inference(rgb_image_path, threshold=threshold)
        assert len(r_high["detections"]) <= len(r_low["detections"])