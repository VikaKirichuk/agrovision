import torch
import numpy as np
from PIL import Image
import segmentation_models_pytorch as smp
import torch.nn.functional as F
import base64, io, os

CLASSES = [
    'double_plant', 'drydown', 'endrow', 'nutrient_deficiency',
    'planter_skip', 'water', 'waterway', 'weed_cluster'
]

LABELS_UA = {
    'double_plant':        'Подвійне посадження',
    'drydown':             'Висихання рослин',
    'endrow':              'Пошкодження кінця ряду',
    'nutrient_deficiency': 'Нестача поживних речовин',
    'planter_skip':        'Зріджені рослини',
    'water':               'Застій води',
    'waterway':            'Водотік',
    'weed_cluster':        "Бур'яни",
}

ADVICE = {
    'double_plant':        'Перевірте налаштування сівалки — можливе пересівання.',
    'drydown':             'Перевірте систему зрошення на цій ділянці.',
    'endrow':              'Зверніть увагу на техніку розворотів при обробці.',
    'nutrient_deficiency': 'Рекомендується агрохімічний аналіз ґрунту.',
    'planter_skip':        'Перевірте сівалку на засмічення або збій подачі насіння.',
    'water':               'Потрібен дренаж або перевірка мікрорельєфу поля.',
    'waterway':            'Природний водотік — враховуйте при плануванні обробки.',
    'weed_cluster':        'Рекомендується локальне гербіцидне оброблення.',
}

COLORS = [
    (100, 100, 255), (255, 200, 0), (100, 255, 100),
    (0, 255, 255),   (200, 100, 255),
    (0, 100, 255),   (0, 255, 200), (100, 255, 200),
]

MODEL_PATH  = os.path.join(os.path.dirname(__file__), "best_unet_efficientnet_b4-2.pth")
IMG_SIZE    = 512
NUM_CLASSES = len(CLASSES)

MEAN = np.array([0.485, 0.456, 0.406, 0.5], dtype=np.float32)
STD  = np.array([0.229, 0.224, 0.225, 0.5], dtype=np.float32)

_model = None


def load_model():
    global _model
    if _model is not None:
        return _model
    model = smp.create_model(
        arch            = 'segformer',
        encoder_name    = 'mit_b2',
        encoder_weights = None,
        in_channels     = 4,
        classes         = NUM_CLASSES,
    )
    checkpoint = torch.load(MODEL_PATH, map_location="cpu")
    state = checkpoint.get("model_state", checkpoint)
    state = {k.replace("module.", ""): v for k, v in state.items()}
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing:
        print(f" Відсутні ключі ({len(missing)}): {missing[:5]}")
    if unexpected:
        print(f" Зайві ключі ({len(unexpected)}): {unexpected[:5]}")
    model.eval()
    _model = model
    print("✅ SegFormer-B2 (4-ch, smp) завантажено успішно")
    return _model


def preprocess(image_path: str) -> torch.Tensor:
    img = Image.open(image_path).convert("RGB")
    img = img.resize((IMG_SIZE, IMG_SIZE))

    rgb = np.array(img).astype(np.float32) / 255.0
    nir = rgb[:, :, 0:1].copy()                    # NIR ≈ R-канал
    image = np.concatenate([rgb, nir], axis=2)      # (H, W, 4)
    image = (image - MEAN) / STD

    return torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0).float()


def run_inference(image_path: str, threshold: float = 0.4) -> dict:
    model  = load_model()
    tensor = preprocess(image_path)

    with torch.no_grad():
        logits = model(tensor)                      # smp повертає тензор напряму
        if logits.shape[-1] != IMG_SIZE:
            logits = F.interpolate(
                logits,
                size=(IMG_SIZE, IMG_SIZE),
                mode="bilinear",
                align_corners=False,
            )
        probs = torch.sigmoid(logits)[0]            # (8, 512, 512)

    total_pixels = IMG_SIZE * IMG_SIZE
    detections   = []
    mask_rgb     = np.zeros((IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8)

    for i, cls in enumerate(CLASSES):
        prob_map = probs[i].numpy()
        binary   = prob_map > threshold
        area_px  = int(binary.sum())

        if area_px > 0:
            detections.append({
                "class":      cls,
                "label_ua":   LABELS_UA[cls],
                "area_pct":   round(area_px / total_pixels * 100, 1),
                "confidence": round(float(prob_map[binary].mean()), 2),
                "advice":     ADVICE[cls],
            })
            mask_rgb[binary] = COLORS[i]

    orig      = Image.open(image_path).convert("RGB").resize((IMG_SIZE, IMG_SIZE))
    orig_arr  = np.array(orig)
    overlay   = orig_arr.copy()
    mask_bool = mask_rgb.sum(axis=2) > 0
    overlay[mask_bool] = (
        orig_arr[mask_bool] * 0.5 + mask_rgb[mask_bool] * 0.5
    ).astype(np.uint8)

    buf = io.BytesIO()
    Image.fromarray(overlay).save(buf, format="PNG")

    return {
        "detections":  detections,
        "mask_base64": base64.b64encode(buf.getvalue()).decode("utf-8"),
    }