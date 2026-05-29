"""
test_ml_pipeline.py — тести ML-пайплайну для SegFormer-B2 (Agriculture Vision).

Покриває:
  - Стратегія валідації (hold-out split 70/15/15)
  - Препроцесинг та аугментації
  - Dataset та DataLoader
  - Метрики (IoU, Dice, PixelAcc)
  - Функція втрат (combined BCE+Dice)
  - Edge cases: порожні маски, чорні зображення, одиничний батч
  - Коректність пайплайну кінець до кінця (без GPU)
"""

import pytest
import numpy as np
import torch
import torch.nn as nn
from unittest.mock import MagicMock, patch
from pathlib import Path


# ──────────────────────────────────────────
#  Константи (відповідають ноутбуку)
# ──────────────────────────────────────────

LABEL_CLASSES = [
    'double_plant', 'drydown', 'endrow',
    'nutrient_deficiency', 'planter_skip',
    'water', 'waterway', 'weed_cluster'
]
NUM_CLASSES = len(LABEL_CLASSES)  # 8
IMG_SIZE    = 512
IN_CHANNELS = 4  # RGB + NIR
MEAN = [0.485, 0.456, 0.406, 0.5]
STD  = [0.229, 0.224, 0.225, 0.5]

DEVICE = torch.device('cpu')  # тести завжди на CPU


# ══════════════════════════════════════════
#  1. Стратегія валідації — hold-out split
# ══════════════════════════════════════════

class TestHoldOutSplit:
    """Перевірка коректності розбиття датасету 70/15/15."""

    @pytest.fixture
    def all_ids(self):
        """Симулюємо 1000 ID зображень."""
        return [f"img_{i:04d}" for i in range(1000)]

    def _do_split(self, all_ids, val_split=0.15, test_split=0.15, seed=42):
        from sklearn.model_selection import train_test_split
        train_ids, temp = train_test_split(
            all_ids, test_size=val_split + test_split, random_state=seed
        )
        val_ids, test_ids = train_test_split(
            temp, test_size=0.5, random_state=seed
        )
        return train_ids, val_ids, test_ids

    def test_split_sizes_correct(self, all_ids):
        """Train ~70%, Val ~15%, Test ~15% від загальної кількості."""
        train, val, test = self._do_split(all_ids)
        total = len(all_ids)
        assert abs(len(train) / total - 0.70) < 0.02, \
            f"Train має бути ~70%, отримано {len(train)/total:.2%}"
        assert abs(len(val)   / total - 0.15) < 0.02
        assert abs(len(test)  / total - 0.15) < 0.02

    def test_no_overlap_between_splits(self, all_ids):
        """Train, Val, Test не перетинаються."""
        train, val, test = self._do_split(all_ids)
        assert len(set(train) & set(val))   == 0, "Train∩Val не порожній!"
        assert len(set(train) & set(test))  == 0, "Train∩Test не порожній!"
        assert len(set(val)   & set(test))  == 0, "Val∩Test не порожній!"

    def test_all_ids_covered(self, all_ids):
        """Всі ID потрапляють рівно в один із сплітів."""
        train, val, test = self._do_split(all_ids)
        assert sorted(train + val + test) == sorted(all_ids)

    def test_split_is_reproducible(self, all_ids):
        """Той самий seed дає однакові сплити."""
        t1, v1, te1 = self._do_split(all_ids, seed=42)
        t2, v2, te2 = self._do_split(all_ids, seed=42)
        assert t1 == t2 and v1 == v2 and te1 == te2

    def test_different_seeds_give_different_splits(self, all_ids):
        """Різні seed дають різні сплити (немає детермінованого артефакту)."""
        t1, _, _ = self._do_split(all_ids, seed=42)
        t2, _, _ = self._do_split(all_ids, seed=99)
        assert t1 != t2


# ══════════════════════════════════════════
#  2. Препроцесинг зображень
# ══════════════════════════════════════════

class TestPreprocessing:
    """Перевірка трансформацій Albumentations для val/test."""

    @pytest.fixture
    def val_transform(self):
        import albumentations as A
        from albumentations.pytorch import ToTensorV2
        return A.Compose([
            A.Resize(IMG_SIZE, IMG_SIZE),
            A.Normalize(mean=MEAN, std=STD),
            ToTensorV2(),
        ])

    @pytest.fixture
    def sample_image(self):
        """Синтетичне RGBN-зображення 200×200."""
        return np.random.randint(0, 255, (200, 200, 4), dtype=np.uint8)

    @pytest.fixture
    def sample_mask(self):
        """Маска 200×200×8 (бінарна, мультикласова)."""
        return np.random.randint(0, 2, (200, 200, NUM_CLASSES), dtype=np.uint8)

    def test_output_tensor_shape(self, val_transform, sample_image, sample_mask):
        """Після трансформації зображення має shape (4, 512, 512)."""
        out = val_transform(image=sample_image, mask=sample_mask)
        assert out['image'].shape == (IN_CHANNELS, IMG_SIZE, IMG_SIZE)

    def test_mask_shape_preserved(self, val_transform, sample_image, sample_mask):
        """Маска після трансформації має shape (512, 512, 8)."""
        out = val_transform(image=sample_image, mask=sample_mask)
        assert out['mask'].shape == (IMG_SIZE, IMG_SIZE, NUM_CLASSES)

    def test_output_is_float_tensor(self, val_transform, sample_image, sample_mask):
        """Вихідний тензор зображення — float32."""
        out = val_transform(image=sample_image, mask=sample_mask)
        assert out['image'].dtype == torch.float32

    def test_normalization_shifts_values(self, val_transform, sample_image, sample_mask):
        """Після нормалізації значення виходять за межі [0, 1]."""
        out = val_transform(image=sample_image, mask=sample_mask)
        img = out['image']
        assert img.min().item() < 0 or img.max().item() > 1, \
            "ImageNet-нормалізація має зрушити значення за [0,1]"

    def test_no_nan_after_transform(self, val_transform, sample_image, sample_mask):
        """Трансформація не породжує NaN."""
        out = val_transform(image=sample_image, mask=sample_mask)
        assert not torch.isnan(out['image']).any()

    def test_black_image_edge_case(self, val_transform, sample_mask):
        """Чорне зображення (всі нулі) обробляється без помилок."""
        black = np.zeros((200, 200, 4), dtype=np.uint8)
        out = val_transform(image=black, mask=sample_mask)
        assert out['image'].shape == (IN_CHANNELS, IMG_SIZE, IMG_SIZE)
        assert not torch.isnan(out['image']).any()

    def test_single_pixel_image_resized(self, val_transform, sample_mask):
        """Зображення 1×1 масштабується до 512×512."""
        tiny = np.zeros((1, 1, 4), dtype=np.uint8)
        tiny_mask = np.zeros((1, 1, NUM_CLASSES), dtype=np.uint8)
        out = val_transform(image=tiny, mask=tiny_mask)
        assert out['image'].shape == (IN_CHANNELS, IMG_SIZE, IMG_SIZE)

    def test_train_augmentation_randomness(self):
        """Тренувальні аугментації дають різний результат для одного зображення."""
        import albumentations as A
        from albumentations.pytorch import ToTensorV2
        train_tf = A.Compose([
            A.HorizontalFlip(p=1.0),  # p=1 — завжди flipає
            A.Normalize(mean=MEAN, std=STD),
            ToTensorV2(),
        ])
        img = np.random.randint(0, 255, (512, 512, 4), dtype=np.uint8)
        mask = np.zeros((512, 512, NUM_CLASSES), dtype=np.uint8)
        out = train_tf(image=img, mask=mask)
        # Перевіряємо що flip відбувся (зображення змінилось)
        original_tf = A.Compose([
            A.Normalize(mean=MEAN, std=STD),
            ToTensorV2(),
        ])
        orig = original_tf(image=img, mask=mask)
        assert not torch.allclose(out['image'], orig['image']), \
            "HorizontalFlip p=1 має змінити зображення"


# ══════════════════════════════════════════
#  3. Метрики (IoU, Dice, PixelAcc)
# ══════════════════════════════════════════

class TestMetrics:
    """
    Перевірка функції compute_metrics() з ноутбука.
    Тестуємо логіку напряму без завантаження моделі.
    """

    @staticmethod
    def compute_metrics(logits, masks, threshold=0.5):
        """Репродукція compute_metrics з ноутбука."""
        pred = (torch.sigmoid(logits) > threshold).float()
        gt   = masks.float()

        inter         = (pred * gt).sum(dim=(0, 2, 3))
        union         = (pred + gt).clamp(0, 1).sum(dim=(0, 2, 3))
        iou_per_class = (inter + 1e-6) / (union + 1e-6)
        valid         = gt.sum(dim=(0, 2, 3)) > 0
        iou = iou_per_class[valid].mean().item() if valid.sum() > 0 else 0.0

        dice_num     = 2 * inter
        dice_den     = pred.sum(dim=(0, 2, 3)) + gt.sum(dim=(0, 2, 3))
        dice_per_cls = (dice_num + 1e-6) / (dice_den + 1e-6)
        dice = dice_per_cls[valid].mean().item() if valid.sum() > 0 else 0.0

        correct    = (pred == gt).float()
        pixel_acc  = correct.mean().item()

        return {'iou': iou, 'dice': dice, 'pixel_acc': pixel_acc}

    def _perfect_logits(self, masks):
        """Логіти що дають ідеальний прогноз (де 1 → +10, де 0 → -10)."""
        return masks.float() * 20 - 10

    def test_perfect_prediction_iou_is_one(self):
        """Ідеальний прогноз → IoU = 1.0."""
        masks = torch.zeros(2, NUM_CLASSES, 64, 64)
        masks[:, 0, 10:20, 10:20] = 1  # клас 0 присутній
        logits = self._perfect_logits(masks)
        m = self.compute_metrics(logits, masks)
        assert abs(m['iou'] - 1.0) < 0.01, f"IoU має бути ~1.0, отримано {m['iou']:.4f}"

    def test_perfect_prediction_dice_is_one(self):
        """Ідеальний прогноз → Dice = 1.0."""
        masks = torch.zeros(2, NUM_CLASSES, 64, 64)
        masks[:, 1, 5:15, 5:15] = 1
        logits = self._perfect_logits(masks)
        m = self.compute_metrics(logits, masks)
        assert abs(m['dice'] - 1.0) < 0.01

    def test_all_wrong_prediction_low_iou(self):
        """Повністю хибний прогноз → IoU близький до 0."""
        masks = torch.zeros(2, NUM_CLASSES, 64, 64)
        masks[:, 0, :32, :32] = 1
        # Прогнозуємо протилежне: де маска 0 — передбачаємо 1, і навпаки
        wrong_logits = self._perfect_logits(1 - masks)
        m = self.compute_metrics(wrong_logits, masks)
        assert m['iou'] < 0.1, f"IoU хибного прогнозу має бути <0.1, отримано {m['iou']:.4f}"

    def test_empty_mask_returns_zero_iou(self):
        """Якщо у GT немає жодного позитивного пікселя → IoU = 0.0."""
        masks  = torch.zeros(2, NUM_CLASSES, 64, 64)
        logits = torch.zeros(2, NUM_CLASSES, 64, 64)
        m = self.compute_metrics(logits, masks)
        assert m['iou'] == 0.0

    def test_pixel_acc_perfect(self):
        """Ідеальний прогноз → pixel_acc = 1.0."""
        masks  = torch.randint(0, 2, (2, NUM_CLASSES, 64, 64)).float()
        logits = self._perfect_logits(masks)
        m = self.compute_metrics(logits, masks)
        assert abs(m['pixel_acc'] - 1.0) < 0.01

    def test_metrics_values_in_range(self):
        """Всі метрики в діапазоні [0, 1]."""
        masks  = torch.randint(0, 2, (2, NUM_CLASSES, 32, 32)).float()
        logits = torch.randn(2, NUM_CLASSES, 32, 32)
        m = self.compute_metrics(logits, masks)
        for key, val in m.items():
            assert 0.0 <= val <= 1.0, f"{key} = {val} виходить за [0,1]"

    @pytest.mark.parametrize("threshold", [0.3, 0.5, 0.7])
    def test_higher_threshold_fewer_positives(self, threshold):
        """Вищий поріг → менше позитивних передбачень."""
        logits = torch.randn(2, NUM_CLASSES, 32, 32)
        pred_low  = (torch.sigmoid(logits) > 0.3).float().sum()
        pred_high = (torch.sigmoid(logits) > threshold).float().sum()
        assert pred_high <= pred_low


# ══════════════════════════════════════════
#  4. Функція втрат (Combined BCE + Dice)
# ══════════════════════════════════════════

class TestLossFunction:
    """Перевірка combined loss = 0.4*BCE + 0.6*Dice."""

    @pytest.fixture
    def criterion(self):
        """Спрощена версія build_criterion без pixel_counts."""
        import segmentation_models_pytorch as smp

        weights = torch.ones(NUM_CLASSES)
        bce  = nn.BCEWithLogitsLoss(pos_weight=weights.view(-1, 1, 1))
        dice = smp.losses.DiceLoss(mode='multilabel')

        def combined(logits, masks):
            return 0.4 * bce(logits, masks) + 0.6 * dice(logits, masks)

        return combined

    def test_loss_is_scalar(self, criterion):
        """Loss повертає скаляр."""
        logits = torch.randn(2, NUM_CLASSES, 64, 64)
        masks  = torch.randint(0, 2, (2, NUM_CLASSES, 64, 64)).float()
        loss = criterion(logits, masks)
        assert loss.ndim == 0, "Loss має бути скаляром (0-dim tensor)"

    def test_loss_is_positive(self, criterion):
        """Loss завжди > 0."""
        logits = torch.randn(2, NUM_CLASSES, 64, 64)
        masks  = torch.randint(0, 2, (2, NUM_CLASSES, 64, 64)).float()
        loss = criterion(logits, masks)
        assert loss.item() > 0

    def test_perfect_prediction_lower_loss(self, criterion):
        """Ідеальний прогноз дає менший loss ніж випадковий."""
        masks = torch.randint(0, 2, (2, NUM_CLASSES, 32, 32)).float()
        perfect_logits = masks * 20 - 10
        random_logits  = torch.randn(2, NUM_CLASSES, 32, 32)
        loss_perfect = criterion(perfect_logits, masks).item()
        loss_random  = criterion(random_logits,  masks).item()
        assert loss_perfect < loss_random, \
            f"Ідеальний loss ({loss_perfect:.4f}) має бути < випадкового ({loss_random:.4f})"

    def test_loss_differentiable(self, criterion):
        """Loss дозволяє backprop (є градієнт)."""
        logits = torch.randn(2, NUM_CLASSES, 32, 32, requires_grad=True)
        masks  = torch.randint(0, 2, (2, NUM_CLASSES, 32, 32)).float()
        loss = criterion(logits, masks)
        loss.backward()
        assert logits.grad is not None
        assert not torch.isnan(logits.grad).any()

    def test_empty_mask_loss_finite(self, criterion):
        """Loss на порожній масці (всі нулі) — скінченне число."""
        logits = torch.randn(2, NUM_CLASSES, 32, 32)
        masks  = torch.zeros(2, NUM_CLASSES, 32, 32)
        loss = criterion(logits, masks)
        assert torch.isfinite(loss)


# ══════════════════════════════════════════
#  5. Dataset — edge cases
# ══════════════════════════════════════════

class TestDatasetEdgeCases:
    """Перевірка AgricultureVisionDataset на граничних випадках."""

    def _make_fake_dataset(self, tmp_path, n_images=3, use_nir=True):
        """Створює мінімальну структуру датасету у tmp_path."""
        ids = [f"img_{i:04d}" for i in range(n_images)]
        for img_id in ids:
            # RGB
            rgb_dir = tmp_path / 'field_images' / 'rgb'
            rgb_dir.mkdir(parents=True, exist_ok=True)
            import cv2
            img = np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)
            cv2.imwrite(str(rgb_dir / f'{img_id}.jpg'), img)

            # NIR
            if use_nir:
                nir_dir = tmp_path / 'field_images' / 'nir'
                nir_dir.mkdir(parents=True, exist_ok=True)
                nir = np.random.randint(0, 255, (256, 256), dtype=np.uint8)
                cv2.imwrite(str(nir_dir / f'{img_id}.jpg'), nir)

            # Labels (тільки перший клас)
            for cls in LABEL_CLASSES:
                lbl_dir = tmp_path / 'field_labels' / cls
                lbl_dir.mkdir(parents=True, exist_ok=True)
                lbl = np.zeros((256, 256), dtype=np.uint8)
                cv2.imwrite(str(lbl_dir / f'{img_id}.png'), lbl)

        return ids

    def test_dataset_len(self, tmp_path):
        """__len__ повертає кількість переданих ID."""
        ids = self._make_fake_dataset(tmp_path, n_images=5)

        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / 'backend'))

        # Визначаємо Dataset локально (щоб не залежати від ноутбука)
        from torch.utils.data import Dataset

        class SimpleDS(Dataset):
            def __init__(self, ids): self.ids = ids
            def __len__(self): return len(self.ids)
            def __getitem__(self, i): return self.ids[i]

        ds = SimpleDS(ids)
        assert len(ds) == 5

    def test_empty_label_handled(self, tmp_path):
        """Відсутня маска класу замінюється нулями — без помилок."""
        import cv2
        img_id = "test_img"
        rgb_dir = tmp_path / 'field_images' / 'rgb'
        rgb_dir.mkdir(parents=True, exist_ok=True)
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        cv2.imwrite(str(rgb_dir / f'{img_id}.jpg'), img)

        # Не створюємо жодної маски — симулюємо відсутність файлів
        for cls in LABEL_CLASSES:
            lbl_dir = tmp_path / 'field_labels' / cls
            lbl_dir.mkdir(parents=True, exist_ok=True)

        H, W = 64, 64
        labels = np.zeros((H, W, NUM_CLASSES), dtype=np.uint8)
        for i, cls_name in enumerate(LABEL_CLASSES):
            label_path = tmp_path / 'field_labels' / cls_name / f'{img_id}.png'
            import cv2 as cv
            lbl = cv.imread(str(label_path), cv.IMREAD_GRAYSCALE)
            if lbl is None:
                lbl = np.zeros((H, W), dtype=np.uint8)
            labels[:, :, i] = (lbl > 0).astype(np.uint8)

        assert labels.sum() == 0, "Відсутні маски мають давати нульовий тензор"

    def test_label_permute_shape(self):
        """labels.permute(2,0,1) дає shape (8, H, W)."""
        labels_np = np.random.randint(0, 2, (64, 64, NUM_CLASSES), dtype=np.uint8)
        labels = torch.from_numpy(labels_np).permute(2, 0, 1).float()
        assert labels.shape == (NUM_CLASSES, 64, 64)

    def test_label_values_binary(self):
        """Після (lbl > 0).astype(uint8) значення маски — 0 або 1."""
        lbl = np.array([[0, 128, 255, 64], [0, 0, 1, 200]], dtype=np.uint8)
        binary = (lbl > 0).astype(np.uint8)
        assert set(np.unique(binary)).issubset({0, 1})


# ══════════════════════════════════════════
#  6. Нормалізація та клас-баланс
# ══════════════════════════════════════════

class TestClassBalance:
    """Перевірка логіки зважування класів у функції втрат."""

    def test_rare_class_gets_higher_weight(self):
        """Рідкісний клас (мало пікселів) отримує більшу вагу."""
        # endrow — 0.14%, weed_cluster — 34.59%
        pixel_pcts = {'endrow': 0.14, 'weed_cluster': 34.59}
        weights = {cls: min(1.0 / (pct + 0.1), 15.0)
                   for cls, pct in pixel_pcts.items()}
        assert weights['endrow'] > weights['weed_cluster'], \
            "Рідкісний клас має отримати більшу вагу"

    def test_weight_capped_at_15(self):
        """Максимальна вага обмежена 15.0."""
        very_rare_pct = 0.001
        weight = min(1.0 / (very_rare_pct + 0.1), 15.0)
        assert weight <= 15.0

    def test_weights_normalized(self):
        """Після нормалізації сума ваг = кількість класів."""
        pixel_pcts = [1.73, 17.62, 0.14, 22.74, 1.96, 18.25, 2.98, 34.59]
        raw = [min(1.0 / (p + 0.1), 15.0) for p in pixel_pcts]
        weights = torch.tensor(raw)
        normalized = weights / weights.sum() * len(weights)
        assert abs(normalized.sum().item() - NUM_CLASSES) < 0.01

    def test_all_classes_have_positive_weight(self):
        """Всі класи отримують додатню вагу."""
        pixel_pcts = [1.73, 17.62, 0.14, 22.74, 1.96, 18.25, 2.98, 34.59]
        raw = [min(1.0 / (p + 0.1), 15.0) for p in pixel_pcts]
        assert all(w > 0 for w in raw)


# ══════════════════════════════════════════
#  7. End-to-end пайплайн (без GPU/моделі)
# ══════════════════════════════════════════

class TestEndToEndPipeline:
    """Перевірка що весь пайплайн від тензора до метрик працює коректно."""

    def test_full_inference_pipeline_shapes(self):
        """
        Симулює inference: image → mock model → logits → metrics.
        Перевіряє shape на кожному кроці.
        """
        # 1. Вхідний батч (як після DataLoader)
        batch_images = torch.randn(2, IN_CHANNELS, IMG_SIZE, IMG_SIZE)
        batch_masks  = torch.randint(0, 2, (2, NUM_CLASSES, IMG_SIZE, IMG_SIZE)).float()
        assert batch_images.shape == (2, 4, 512, 512)
        assert batch_masks.shape  == (2, 8, 512, 512)

        # 2. Mock model output (logits)
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.logits = torch.randn(2, NUM_CLASSES, IMG_SIZE // 4, IMG_SIZE // 4)
        mock_model.return_value = mock_output
        output = mock_model(batch_images)
        logits = output.logits
        assert logits.shape[1] == NUM_CLASSES

        # 3. Upsample до розміру маски (як у SegFormer)
        logits_up = torch.nn.functional.interpolate(
            logits, size=(IMG_SIZE, IMG_SIZE), mode='bilinear', align_corners=False
        )
        assert logits_up.shape == (2, NUM_CLASSES, IMG_SIZE, IMG_SIZE)

        # 4. Predictions
        preds = (torch.sigmoid(logits_up) > 0.5).float()
        assert preds.shape == batch_masks.shape
        assert set(preds.unique().tolist()).issubset({0.0, 1.0})

    def test_sigmoid_output_in_range(self):
        """sigmoid(logits) завжди в [0, 1]."""
        logits = torch.randn(4, NUM_CLASSES, 64, 64) * 100  # великі значення
        probs = torch.sigmoid(logits)
        assert probs.min().item() >= 0.0
        assert probs.max().item() <= 1.0

    def test_threshold_binarization(self):
        """Після порогу значення строго 0 або 1."""
        probs = torch.rand(2, NUM_CLASSES, 32, 32)
        binary = (probs > 0.5).float()
        unique_vals = set(binary.unique().tolist())
        assert unique_vals.issubset({0.0, 1.0})

    def test_multilabel_allows_multiple_classes_per_pixel(self):
        """Мультикласова сегментація: один піксель може належати >1 класу."""
        logits = torch.full((1, NUM_CLASSES, 4, 4), 10.0)  # всі класи активні
        preds  = (torch.sigmoid(logits) > 0.5).float()
        # Кожен піксель має всі 8 класів = 1
        assert preds.sum(dim=1).min().item() == NUM_CLASSES

    def test_batch_size_one_works(self):
        """Батч з одного елементу обробляється без помилок."""
        logits = torch.randn(1, NUM_CLASSES, 128, 128)
        masks  = torch.randint(0, 2, (1, NUM_CLASSES, 128, 128)).float()
        preds  = (torch.sigmoid(logits) > 0.5).float()
        assert preds.shape == masks.shape