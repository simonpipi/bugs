#!/usr/bin/env python3
import argparse
import csv
import json
import random
import sys
from datetime import datetime
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageSequence


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CAPTCHA_DIR = SCRIPT_DIR / "captchas"
DEFAULT_PREVIEW_DIR = SCRIPT_DIR / "captcha_preprocessed"
DEFAULT_LABELS = SCRIPT_DIR / "labels.csv"
DEFAULT_MODEL = SCRIPT_DIR / "captcha_model.pt"
DEFAULT_ERROR_CSV = SCRIPT_DIR / "captcha_errors.csv"
DEFAULT_REVIEW_CSV = SCRIPT_DIR / "captcha_reviews.csv"
DEFAULT_REVIEW_LABELS = SCRIPT_DIR / "labels_reviewed.csv"
DEFAULT_COMPARE_SHEET = SCRIPT_DIR / "captcha_preprocess_compare.png"
DEFAULT_CHARSET = "0123456789abcdefghijklmnopqrstuvwxyz"
DEFAULT_METHOD = "bestframe"
IMAGE_SIZE = (120, 40)
CODE_LENGTH = 4
REVIEW_FIELDS = [
    "filename",
    "prediction",
    "label",
    "corrected_label",
    "is_error",
    "use_for_training",
    "reviewed",
    "notes",
    "updated_at",
]


class CaptchaError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptchaSample:
    filename: str
    label: str


def read_gif_frames(path: Path, size: Tuple[int, int] = IMAGE_SIZE) -> List[Image.Image]:
    image = Image.open(path)
    frames = []
    for frame in ImageSequence.Iterator(image):
        frame = frame.convert("RGB").resize(size, Image.Resampling.BILINEAR)
        frames.append(frame.convert("L"))
    if not frames:
        raise CaptchaError(f"GIF 没有可读取帧: {path}")
    return frames


def fuse_frames(frames: Sequence[Image.Image], method: str = DEFAULT_METHOD) -> Image.Image:
    if method not in {"clean", "bestframe", "median", "darkest", "vote", "motion"}:
        raise CaptchaError(f"不支持的融合方法: {method}")

    if method == "clean":
        return clean_best_frame(frames)

    if method == "bestframe":
        return select_best_frame(frames)

    pixel_rows = [list(get_flat_pixels(frame)) for frame in frames]
    fused = []
    for values in zip(*pixel_rows):
        if method == "median":
            ordered = sorted(values)
            fused.append(ordered[len(ordered) // 2])
        elif method == "darkest":
            fused.append(min(values))
        elif method == "vote":
            dark_count = sum(1 for value in values if value < 165)
            fused.append(0 if dark_count >= max(2, len(values) // 3) else 255)
        else:
            ordered = sorted(values)
            median = ordered[len(ordered) // 2]
            darkest = min(values)
            motion = max(abs(value - median) for value in values)
            fused.append(darkest if darkest < 210 and motion > 18 else 255)

    image = Image.new("L", frames[0].size)
    image.putdata(fused)
    return image


def select_best_frame(frames: Sequence[Image.Image]) -> Image.Image:
    best = None
    best_score = -1
    for frame in frames:
        image = ImageOps.autocontrast(frame)
        pixels = list(get_flat_pixels(image))
        threshold = otsu_threshold(image)
        ink = sum(1 for value in pixels if value < threshold)
        darkness = sum(max(0, threshold - value) for value in pixels if value < threshold)
        score = ink * 2 + darkness
        if score > best_score:
            best_score = score
            best = image
    if best is None:
        raise CaptchaError("未能选择最佳帧")
    return best


def clean_best_frame(frames: Sequence[Image.Image]) -> Image.Image:
    image = select_best_frame(frames)
    image = normalize_gradient_background(image)
    threshold = max(70, min(145, otsu_threshold(image) - 12))
    binary = image.point(lambda value: 0 if value < threshold else 255, mode="1").convert("L")
    binary = filter_connected_components(binary)
    return binary


def normalize_gradient_background(image: Image.Image) -> Image.Image:
    image = ImageOps.autocontrast(image.convert("L"))
    width, height = image.size
    pixels = list(get_flat_pixels(image))
    out = []
    for y in range(height):
        row = pixels[y * width : (y + 1) * width]
        ordered = sorted(row)
        bg = ordered[int(len(ordered) * 0.82)]
        for value in row:
            ink = max(0, bg - value)
            out.append(255 - min(255, ink * 5))
    result = Image.new("L", image.size, 255)
    result.putdata(out)
    return ImageOps.autocontrast(result)


def filter_connected_components(image: Image.Image) -> Image.Image:
    width, height = image.size
    pixels = list(get_flat_pixels(image.convert("L")))
    seen = [False] * len(pixels)
    components = []

    for start, value in enumerate(pixels):
        if seen[start] or value > 0:
            continue
        stack = [start]
        seen[start] = True
        xs = []
        ys = []
        while stack:
            pos = stack.pop()
            x = pos % width
            y = pos // width
            xs.append(x)
            ys.append(y)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if nx < 0 or nx >= width or ny < 0 or ny >= height:
                    continue
                npos = ny * width + nx
                if not seen[npos] and pixels[npos] == 0:
                    seen[npos] = True
                    stack.append(npos)

        area = len(xs)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        comp_w = max_x - min_x + 1
        comp_h = max_y - min_y + 1
        components.append(
            {
                "area": area,
                "bbox": (min_x, min_y, max_x + 1, max_y + 1),
                "w": comp_w,
                "h": comp_h,
                "score": area + comp_h * 10 + comp_w * 4,
            }
        )

    candidates = [
        comp
        for comp in components
        if comp["area"] >= 18
        and comp["h"] >= 8
        and comp["w"] >= 3
        and comp["h"] <= 38
        and comp["w"] <= 38
    ]
    if len(candidates) < CODE_LENGTH:
        candidates = [comp for comp in components if comp["area"] >= 10 and comp["h"] >= 5 and comp["w"] >= 2]

    selected = sorted(candidates, key=lambda comp: comp["score"], reverse=True)[: max(8, CODE_LENGTH)]
    selected_indexes = set()
    for comp in selected:
        left, top, right, bottom = comp["bbox"]
        for y in range(top, bottom):
            for x in range(left, right):
                pos = y * width + x
                if pixels[pos] == 0:
                    selected_indexes.add(pos)

    cleaned = [0 if index in selected_indexes else 255 for index in range(len(pixels))]
    result = Image.new("L", image.size, 255)
    result.putdata(cleaned)
    return result.filter(ImageFilter.MinFilter(size=3))


def get_flat_pixels(image: Image.Image):
    if hasattr(image, "get_flattened_data"):
        return image.get_flattened_data()
    return image.getdata()


def otsu_threshold(image: Image.Image) -> int:
    hist = image.histogram()
    total = sum(hist)
    sum_total = sum(i * count for i, count in enumerate(hist))
    sum_back = 0
    weight_back = 0
    max_var = -1.0
    threshold = 160

    for value, count in enumerate(hist):
        weight_back += count
        if weight_back == 0:
            continue
        weight_fore = total - weight_back
        if weight_fore == 0:
            break
        sum_back += value * count
        mean_back = sum_back / weight_back
        mean_fore = (sum_total - sum_back) / weight_fore
        var_between = weight_back * weight_fore * (mean_back - mean_fore) ** 2
        if var_between > max_var:
            max_var = var_between
            threshold = value
    return threshold


def preprocess_gif(
    path: Path,
    *,
    method: str = DEFAULT_METHOD,
    binary: bool = False,
    denoise: bool = False,
    size: Tuple[int, int] = IMAGE_SIZE,
) -> Image.Image:
    frames = read_gif_frames(path, size=size)
    image = fuse_frames(frames, method=method)
    image = ImageOps.autocontrast(image)
    if denoise:
        image = image.filter(ImageFilter.MedianFilter(size=3))
    if binary:
        threshold = otsu_threshold(image)
        image = image.point(lambda value: 0 if value < threshold else 255, mode="1").convert("L")
    return image


def image_to_tensor(image: Image.Image):
    torch = import_torch()
    pixels = list(get_flat_pixels(ImageOps.invert(image.convert("L"))))
    values = [value / 255.0 for value in pixels]
    return torch.tensor(values, dtype=torch.float32).view(1, IMAGE_SIZE[1], IMAGE_SIZE[0])


def normalize_label(label: str, charset: str, case_sensitive: bool = False) -> str:
    label = label.strip()
    if not case_sensitive:
        label = label.lower()
    if len(label) != CODE_LENGTH:
        raise CaptchaError(f"标签长度必须为 {CODE_LENGTH}: {label!r}")
    invalid = sorted(set(label) - set(charset))
    if invalid:
        raise CaptchaError(f"标签包含字符集外字符 {invalid}: {label!r}")
    return label


def read_labels(path: Path, charset: str, case_sensitive: bool = False) -> List[CaptchaSample]:
    if not path.exists():
        raise FileNotFoundError(f"标签文件不存在: {path}")

    samples = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        for row_number, row in enumerate(reader, 1):
            if not row or not "".join(row).strip():
                continue
            if row_number == 1 and row[0].strip().lower() == "filename":
                continue
            if len(row) < 2:
                raise CaptchaError(f"标签文件第 {row_number} 行缺少 label: {row}")
            filename = row[0].strip()
            label = normalize_label(row[1], charset, case_sensitive=case_sensitive)
            samples.append(CaptchaSample(filename=filename, label=label))

    if not samples:
        raise CaptchaError(f"标签文件没有有效样本: {path}")
    return samples


def read_label_map(path: Path, charset: str, case_sensitive: bool = False) -> Dict[str, str]:
    if not path.exists():
        return {}

    label_map: Dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        for row_number, row in enumerate(reader, 1):
            if not row or not "".join(row).strip():
                continue
            if row_number == 1 and row[0].strip().lower() == "filename":
                continue
            if len(row) < 2:
                continue
            filename = row[0].strip()
            label = row[1].strip()
            if not label:
                continue
            label_map[filename] = normalize_label(label, charset, case_sensitive=case_sensitive)
    return label_map


def read_review_rows(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}

    rows: Dict[str, dict] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            filename = (row.get("filename") or "").strip()
            if not filename:
                continue
            rows[filename] = {
                "filename": filename,
                "prediction": (row.get("prediction") or "").strip(),
                "label": (row.get("label") or "").strip(),
                "corrected_label": (row.get("corrected_label") or "").strip(),
                "is_error": str(row.get("is_error") or "").strip().lower() in {"1", "true", "yes", "y", "on"},
                "use_for_training": str(row.get("use_for_training") or "").strip().lower() in {"1", "true", "yes", "y", "on"},
                "reviewed": str(row.get("reviewed") or "").strip().lower() in {"1", "true", "yes", "y", "on"},
                "notes": (row.get("notes") or "").strip(),
                "updated_at": (row.get("updated_at") or "").strip(),
            }
    return rows


def write_review_rows(path: Path, rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in REVIEW_FIELDS})


def timestamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_label_template(captcha_dir: Path, labels_path: Path, overwrite: bool = False) -> None:
    if labels_path.exists() and not overwrite:
        raise FileExistsError(f"标签文件已存在，未覆盖: {labels_path}")
    files = sorted(captcha_dir.glob("*.gif"))
    if not files:
        raise CaptchaError(f"目录里没有 GIF 验证码: {captcha_dir}")

    labels_path.parent.mkdir(parents=True, exist_ok=True)
    with labels_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["filename", "label"])
        for path in files:
            writer.writerow([path.name, ""])
    print(f"已生成标签模板: {labels_path}，样本数: {len(files)}")


def preprocess_directory(
    captcha_dir: Path,
    output_dir: Path,
    *,
    method: str = DEFAULT_METHOD,
    binary: bool = False,
    denoise: bool = False,
    limit: Optional[int] = None,
) -> None:
    files = sorted(captcha_dir.glob("*.gif"))
    if limit:
        files = files[:limit]
    if not files:
        raise CaptchaError(f"目录里没有 GIF 验证码: {captcha_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for path in files:
        image = preprocess_gif(path, method=method, binary=binary, denoise=denoise)
        output_path = output_dir / f"{path.stem}.png"
        image.save(output_path)
    print(f"已输出预处理图片 {len(files)} 张到: {output_dir}")


def make_compare_sheet(
    captcha_dir: Path,
    output_path: Path,
    *,
    limit: int = 8,
    binary: bool = False,
) -> None:
    files = sorted(captcha_dir.glob("*.gif"))[:limit]
    if not files:
        raise CaptchaError(f"目录里没有 GIF 验证码: {captcha_dir}")

    methods = ["clean", "bestframe", "median", "darkest", "motion", "vote"]
    cell_w, cell_h = IMAGE_SIZE
    sheet = Image.new("L", (cell_w * len(methods), cell_h * len(files)), 255)
    for row, path in enumerate(files):
        for col, method in enumerate(methods):
            image = preprocess_gif(path, method=method, binary=binary)
            sheet.paste(image, (col * cell_w, row * cell_h))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    print(f"已输出融合方式对比图: {output_path}")


def load_sheet_font(size: int = 18):
    for font_path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        path = Path(font_path)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                pass
    return ImageFont.load_default()


def make_label_sheet(
    captcha_dir: Path,
    output_path: Path,
    *,
    method: str = DEFAULT_METHOD,
    scale: int = 3,
    columns: int = 2,
    limit: Optional[int] = None,
) -> None:
    files = sorted(captcha_dir.glob("*.gif"))
    if limit:
        files = files[:limit]
    if not files:
        raise CaptchaError(f"目录里没有 GIF 验证码: {captcha_dir}")

    image_w, image_h = IMAGE_SIZE
    cell_w = image_w * scale
    cell_h = image_h * scale + 30
    rows = (len(files) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), "white")
    draw = ImageDraw.Draw(sheet)
    font = load_sheet_font()

    for index, path in enumerate(files):
        image = preprocess_gif(path, method=method)
        image = image.resize((image_w * scale, image_h * scale), Image.Resampling.NEAREST)
        image = image.convert("RGB")
        left = (index % columns) * cell_w
        top = (index // columns) * cell_h
        draw.text((left + 8, top + 6), path.name, fill=(0, 0, 0), font=font)
        sheet.paste(image, (left, top + 28))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    print(f"已输出标注辅助图: {output_path}")


def import_torch():
    try:
        import torch
    except ImportError as exc:
        raise CaptchaError("缺少 PyTorch，请先安装 torch") from exc
    return torch


def build_model(num_classes: int):
    torch = import_torch()
    nn = torch.nn

    class CaptchaCNN(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 32, kernel_size=3, padding=1),
                nn.BatchNorm2d(32),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(64, 128, kernel_size=3, padding=1),
                nn.BatchNorm2d(128),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(128, 192, kernel_size=3, padding=1),
                nn.BatchNorm2d(192),
                nn.ReLU(inplace=True),
            )
            self.classifier = nn.Sequential(
                nn.Flatten(),
                nn.Linear(192 * 5 * 15, 512),
                nn.ReLU(inplace=True),
                nn.Dropout(0.25),
            )
            self.heads = nn.ModuleList([nn.Linear(512, num_classes) for _ in range(CODE_LENGTH)])

        def forward(self, x):
            x = self.features(x)
            x = self.classifier(x)
            return [head(x) for head in self.heads]

    return CaptchaCNN()


class CaptchaDataset:
    def __init__(
        self,
        samples: Sequence[CaptchaSample],
        captcha_dir: Path,
        charset: str,
        *,
        method: str = "median",
        binary: bool = False,
        denoise: bool = False,
        augment: bool = False,
    ) -> None:
        self.samples = list(samples)
        self.captcha_dir = captcha_dir
        self.charset = charset
        self.char_to_index = {char: index for index, char in enumerate(charset)}
        self.method = method
        self.binary = binary
        self.denoise = denoise
        self.augment = augment

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        torch = import_torch()
        sample = self.samples[index]
        image_path = self.captcha_dir / sample.filename
        if not image_path.exists():
            raise FileNotFoundError(f"验证码图片不存在: {image_path}")

        image = preprocess_gif(
            image_path,
            method=self.method,
            binary=self.binary,
            denoise=self.denoise,
        )
        if self.augment:
            image = augment_image(image)
        x = image_to_tensor(image)
        y = torch.tensor([self.char_to_index[char] for char in sample.label], dtype=torch.long)
        return x, y


def augment_image(image: Image.Image) -> Image.Image:
    if random.random() < 0.35:
        image = image.filter(ImageFilter.GaussianBlur(radius=random.choice([0.3, 0.5])))
    if random.random() < 0.35:
        delta = random.randint(-12, 12)
        image = image.point(lambda value: max(0, min(255, value + delta)))
    if random.random() < 0.25:
        image = ImageOps.autocontrast(image)
    return image


def split_samples(samples: Sequence[CaptchaSample], val_ratio: float, seed: int):
    if val_ratio < 0 or val_ratio >= 1:
        raise CaptchaError("--val-ratio 必须大于等于 0 且小于 1")
    if val_ratio == 0 or len(samples) <= 1:
        return list(samples), []
    shuffled = list(samples)
    random.Random(seed).shuffle(shuffled)
    val_count = max(1, int(len(shuffled) * val_ratio))
    return shuffled[val_count:], shuffled[:val_count]


def choose_device(name: str):
    torch = import_torch()
    if name != "auto":
        return torch.device(name)
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def train_model(
    *,
    captcha_dir: Path,
    labels_path: Path,
    model_path: Path,
    charset: str,
    case_sensitive: bool,
    method: str,
    binary: bool,
    denoise: bool,
    epochs: int,
    batch_size: int,
    lr: float,
    val_ratio: float,
    seed: int,
    device_name: str,
) -> None:
    torch = import_torch()
    DataLoader = torch.utils.data.DataLoader

    samples = read_labels(labels_path, charset, case_sensitive=case_sensitive)
    train_samples, val_samples = split_samples(samples, val_ratio, seed)
    if not train_samples:
        raise CaptchaError("训练样本为空，请补充标签数据")

    train_set = CaptchaDataset(
        train_samples,
        captcha_dir,
        charset,
        method=method,
        binary=binary,
        denoise=denoise,
        augment=True,
    )
    val_set = CaptchaDataset(
        val_samples,
        captcha_dir,
        charset,
        method=method,
        binary=binary,
        denoise=denoise,
        augment=False,
    )
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False, num_workers=0)

    device = choose_device(device_name)
    model = build_model(len(charset)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    criterion = torch.nn.CrossEntropyLoss()

    best_exact = -1.0
    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"训练样本: {len(train_samples)}，验证样本: {len(val_samples)}，device: {device}")

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        total_batches = 0
        for x, y in train_loader:
            x = x.to(device)
            y = y.to(device)
            outputs = model(x)
            loss = sum(criterion(outputs[pos], y[:, pos]) for pos in range(CODE_LENGTH))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item())
            total_batches += 1

        metrics = evaluate_model(model, val_loader, device) if val_samples else {"char_acc": 0, "exact_acc": 0}
        avg_loss = total_loss / max(1, total_batches)
        print(
            f"epoch {epoch:03d}/{epochs} "
            f"loss={avg_loss:.4f} "
            f"char_acc={metrics['char_acc']:.4f} "
            f"exact_acc={metrics['exact_acc']:.4f}"
        )

        if metrics["exact_acc"] >= best_exact:
            best_exact = metrics["exact_acc"]
            save_checkpoint(model, model_path, charset, method, binary, denoise, case_sensitive)

    print(f"训练完成，最佳模型已保存: {model_path}")


def evaluate_model(model, loader, device) -> dict:
    torch = import_torch()
    model.eval()
    char_total = 0
    char_correct = 0
    exact_total = 0
    exact_correct = 0
    with torch.no_grad():
        for x, y in loader:
            x = x.to(device)
            y = y.to(device)
            outputs = model(x)
            preds = torch.stack([output.argmax(dim=1) for output in outputs], dim=1)
            char_correct += int((preds == y).sum().item())
            char_total += int(y.numel())
            exact_correct += int((preds == y).all(dim=1).sum().item())
            exact_total += int(y.shape[0])
    return {
        "char_acc": char_correct / char_total if char_total else 0.0,
        "exact_acc": exact_correct / exact_total if exact_total else 0.0,
    }


def save_checkpoint(
    model,
    path: Path,
    charset: str,
    method: str,
    binary: bool,
    denoise: bool,
    case_sensitive: bool,
) -> None:
    torch = import_torch()
    torch.save(
        {
            "state_dict": model.state_dict(),
            "charset": charset,
            "method": method,
            "binary": binary,
            "denoise": denoise,
            "case_sensitive": case_sensitive,
            "image_size": IMAGE_SIZE,
            "code_length": CODE_LENGTH,
        },
        path,
    )


def load_checkpoint(path: Path, device_name: str = "auto"):
    torch = import_torch()
    device = choose_device(device_name)
    checkpoint = torch.load(path, map_location=device)
    charset = checkpoint["charset"]
    model = build_model(len(charset)).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return model, checkpoint, device


def predict_image_with_model(model, checkpoint: dict, device_obj, image_path: Path) -> str:
    torch = import_torch()
    image = preprocess_gif(
        image_path,
        method=checkpoint.get("method", DEFAULT_METHOD),
        binary=bool(checkpoint.get("binary", False)),
        denoise=bool(checkpoint.get("denoise", False)),
    )
    x = image_to_tensor(image).unsqueeze(0).to(device_obj)
    charset = checkpoint["charset"]
    with torch.no_grad():
        outputs = model(x)
        indexes = [int(output.argmax(dim=1).item()) for output in outputs]
    return "".join(charset[index] for index in indexes)


def predict_captcha(path: str, model_path: str = str(DEFAULT_MODEL), device: str = "auto") -> str:
    model, checkpoint, device_obj = load_checkpoint(Path(model_path), device)
    return predict_image_with_model(model, checkpoint, device_obj, Path(path))


def predict_many(model_path: Path, image_paths: Iterable[Path], device_name: str) -> None:
    for path in image_paths:
        prediction = predict_captcha(str(path), str(model_path), device=device_name)
        print(f"{path.name},{prediction}")


def evaluate_checkpoint(
    *,
    model_path: Path,
    captcha_dir: Path,
    labels_path: Path,
    error_csv: Path,
    device_name: str,
) -> None:
    model, checkpoint, device = load_checkpoint(model_path, device_name)
    charset = checkpoint["charset"]
    samples = read_labels(labels_path, charset, case_sensitive=bool(checkpoint.get("case_sensitive", False)))
    rows = []
    char_total = 0
    char_correct = 0
    exact_correct = 0

    for sample in samples:
        image_path = captcha_dir / sample.filename
        pred = predict_image_with_model(model, checkpoint, device, image_path)
        ok = pred == sample.label
        exact_correct += int(ok)
        char_total += CODE_LENGTH
        char_correct += sum(1 for a, b in zip(pred, sample.label) if a == b)
        if not ok:
            rows.append([sample.filename, sample.label, pred])

    error_csv.parent.mkdir(parents=True, exist_ok=True)
    with error_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["filename", "label", "prediction"])
        writer.writerows(rows)

    print(f"样本数: {len(samples)}")
    print(f"单字符准确率: {char_correct / max(1, char_total):.4f}")
    print(f"整码准确率: {exact_correct / max(1, len(samples)):.4f}")
    print(f"错误样本已保存: {error_csv}")


def bool_to_csv(value: bool) -> str:
    return "1" if value else "0"


def classify_review_record(record: dict) -> str:
    if record.get("is_error"):
        return "error"
    prediction = record.get("prediction") or ""
    corrected = record.get("corrected_label") or ""
    if not prediction:
        return "no_prediction"
    if not corrected:
        return "pending"
    return "ok" if prediction == corrected else "error"


def apply_review_row(record: dict, row: dict) -> dict:
    merged = dict(record)
    merged.update(
        {
            "corrected_label": row.get("corrected_label", ""),
            "is_error": bool(row.get("is_error", False)),
            "use_for_training": bool(row.get("use_for_training", False)),
            "reviewed": bool(row.get("reviewed", False)),
            "notes": row.get("notes", ""),
            "updated_at": row.get("updated_at", ""),
        }
    )
    merged["status"] = classify_review_record(merged)
    return merged


def summarize_review_records(records: Sequence[dict]) -> dict:
    return {
        "total": len(records),
        "errors": sum(1 for row in records if row.get("status") == "error"),
        "reviewed": sum(1 for row in records if row.get("reviewed")),
        "training": sum(1 for row in records if row.get("use_for_training") and row.get("corrected_label")),
        "no_prediction": sum(1 for row in records if row.get("status") == "no_prediction"),
    }


def build_review_records(
    *,
    captcha_dir: Path,
    labels_path: Path,
    model_path: Path,
    review_csv: Path,
    device_name: str,
) -> Tuple[List[dict], dict]:
    files = sorted(captcha_dir.glob("*.gif"))
    if not files:
        raise CaptchaError(f"目录里没有 GIF 验证码: {captcha_dir}")

    model = None
    checkpoint = None
    device_obj = None
    charset = DEFAULT_CHARSET
    case_sensitive = False
    model_error = ""
    if model_path.exists():
        try:
            model, checkpoint, device_obj = load_checkpoint(model_path, device_name)
            charset = checkpoint["charset"]
            case_sensitive = bool(checkpoint.get("case_sensitive", False))
        except Exception as exc:
            model_error = str(exc)

    labels = read_label_map(labels_path, charset, case_sensitive=case_sensitive)
    reviews = read_review_rows(review_csv)
    records: List[dict] = []

    for path in files:
        prediction = ""
        prediction_error = model_error
        if model is not None and checkpoint is not None and device_obj is not None:
            try:
                prediction = predict_image_with_model(model, checkpoint, device_obj, path)
                prediction_error = ""
            except Exception as exc:
                prediction_error = str(exc)

        label = labels.get(path.name, "")
        review = reviews.get(path.name)
        corrected_label = label or prediction
        is_error = bool(label and prediction and label != prediction)
        reviewed = False
        use_for_training = bool(corrected_label)
        notes = ""
        updated_at = ""

        record = {
            "filename": path.name,
            "image_url": f"/captcha/{quote(path.name)}",
            "prediction": prediction,
            "label": label,
            "corrected_label": corrected_label,
            "is_error": is_error,
            "use_for_training": use_for_training,
            "reviewed": reviewed,
            "notes": notes,
            "updated_at": updated_at,
            "prediction_error": prediction_error,
        }
        record["status"] = classify_review_record(record)
        if review:
            record = apply_review_row(record, review)
        records.append(record)

    meta = {
        "captcha_dir": str(captcha_dir),
        "labels_path": str(labels_path),
        "model_path": str(model_path),
        "review_csv": str(review_csv),
        "charset": charset,
        "case_sensitive": case_sensitive,
        "summary": summarize_review_records(records),
    }
    return records, meta


def export_reviewed_labels(
    *,
    captcha_dir: Path,
    labels_path: Path,
    review_csv: Path,
    output_path: Path,
    charset: str,
    case_sensitive: bool,
) -> dict:
    label_map = read_label_map(labels_path, charset, case_sensitive=case_sensitive)
    reviews = read_review_rows(review_csv)
    review_count = 0
    for filename, row in reviews.items():
        corrected = row.get("corrected_label", "")
        if not row.get("use_for_training") or not corrected:
            continue
        label_map[filename] = normalize_label(corrected, charset, case_sensitive=case_sensitive)
        review_count += 1

    files = sorted(captcha_dir.glob("*.gif"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["filename", "label"])
        for path in files:
            label = label_map.get(path.name)
            if not label:
                continue
            writer.writerow([path.name, label])
            written += 1

    return {
        "output": str(output_path),
        "samples": written,
        "reviewed_samples": review_count,
    }


REVIEW_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>验证码识别结果维护</title>
  <style>
    :root { color-scheme: light; --bg:#f6f7f9; --panel:#ffffff; --text:#18202a; --muted:#667085; --line:#d7dce3; --bad:#b42318; --good:#067647; --blue:#175cd3; --warn:#b54708; }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    header { position: sticky; top: 0; z-index: 5; background: rgba(246,247,249,.94); border-bottom: 1px solid var(--line); backdrop-filter: blur(10px); }
    .bar { max-width: 1280px; margin: 0 auto; padding: 14px 18px; display: grid; grid-template-columns: 1fr auto; gap: 14px; align-items: center; }
    h1 { margin: 0; font-size: 18px; letter-spacing: 0; }
    .meta { color: var(--muted); font-size: 12px; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 760px; }
    .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
    button, input, select, textarea { font: inherit; }
    button { border: 1px solid var(--line); background: #fff; border-radius: 6px; padding: 7px 10px; cursor: pointer; color: var(--text); }
    button.primary { background: var(--blue); border-color: var(--blue); color: #fff; }
    button.danger { color: var(--bad); }
    button:disabled { opacity: .5; cursor: wait; }
    main { max-width: 1280px; margin: 0 auto; padding: 16px 18px 36px; }
    .stats { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 10px; margin-bottom: 12px; }
    .stat { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
    .stat strong { display: block; font-size: 22px; line-height: 1.1; }
    .stat span { color: var(--muted); font-size: 12px; }
    .workspace { display: grid; grid-template-columns: minmax(280px, 360px) minmax(0, 1fr); gap: 14px; align-items: start; }
    .side { position: sticky; top: 86px; max-height: calc(100vh - 108px); overflow: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
    .side-head { padding: 10px; border-bottom: 1px solid var(--line); display: grid; gap: 8px; background: #fff; position: sticky; top: 0; z-index: 2; }
    .toolbar { display: grid; grid-template-columns: 1fr; gap: 8px; align-items: center; }
    .toolbar input, .toolbar select { width: 100%; height: 36px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; background: #fff; }
    .filters { display: flex; gap: 8px; flex-wrap: wrap; }
    .sample-list { display: grid; gap: 0; }
    .sample-item { width: 100%; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; background: #fff; padding: 9px 10px; display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; text-align: left; }
    .sample-item:hover { background: #f8fafc; }
    .sample-item.active { background: #eff6ff; box-shadow: inset 3px 0 0 var(--blue); }
    .sample-no { color: var(--muted); font-size: 12px; min-width: 24px; }
    .sample-main { min-width: 0; display: grid; gap: 2px; }
    .sample-file { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .sample-code { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .detail { min-width: 0; }
    .grid { display: block; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
    .card.active { box-shadow: 0 0 0 3px rgba(23, 92, 211, .18); }
    .card.error { border-color: #fda29b; }
    .card.ok { border-color: #abefc6; }
    .card.pending { border-color: #fedf89; }
    .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 9px 10px; border-bottom: 1px solid var(--line); }
    .file-wrap { min-width: 0; display: grid; gap: 2px; }
    .file { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .review-state { color: var(--muted); font-size: 12px; }
    .badge { border-radius: 999px; padding: 2px 8px; font-size: 12px; white-space: nowrap; background: #eef2f6; color: var(--muted); }
    .badge.error { background: #fee4e2; color: var(--bad); }
    .badge.ok { background: #dcfae6; color: var(--good); }
    .badge.pending { background: #fef0c7; color: var(--warn); }
    .image { background: #fff; border-bottom: 1px solid var(--line); display: flex; align-items: center; justify-content: center; min-height: 142px; padding: 18px; }
    .image img { width: min(520px, 100%); height: 132px; object-fit: contain; image-rendering: auto; }
    .body { padding: 14px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .body label:has(textarea), .checks, .row-actions { grid-column: 1 / -1; }
    label { color: var(--muted); font-size: 12px; display: grid; gap: 4px; }
    .readonly { min-height: 34px; border: 1px solid var(--line); border-radius: 6px; background: #f8fafc; padding: 6px 8px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--text); }
    .code { width: 100%; height: 36px; border: 1px solid var(--line); border-radius: 6px; padding: 0 9px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: 2px; }
    textarea { width: 100%; min-height: 54px; resize: vertical; border: 1px solid var(--line); border-radius: 6px; padding: 7px 9px; }
    .checks { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .check { display: flex; align-items: center; gap: 7px; color: var(--text); font-size: 13px; }
    .row-actions { display: flex; gap: 8px; justify-content: space-between; align-items: center; }
    .empty { text-align: center; color: var(--muted); padding: 38px 0; }
    .toast { position: fixed; right: 18px; bottom: 18px; background: #111827; color: #fff; padding: 10px 12px; border-radius: 6px; display: none; max-width: min(420px, calc(100vw - 36px)); }
    @media (max-width: 760px) {
      .bar { grid-template-columns: 1fr; }
      .actions { justify-content: flex-start; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .workspace { grid-template-columns: 1fr; }
      .side { position: static; max-height: 320px; }
      .body { grid-template-columns: 1fr; }
      .filters { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div>
        <h1>验证码识别结果维护</h1>
        <div class="meta" id="meta"></div>
      </div>
      <div class="actions">
        <button id="refreshBtn">重新识别</button>
        <button id="saveAllBtn">保存全部</button>
        <button id="exportBtn" class="primary">导出训练集</button>
      </div>
    </div>
  </header>
  <main>
    <section class="stats">
      <div class="stat"><strong id="stTotal">0</strong><span>总样本</span></div>
      <div class="stat"><strong id="stErrors">0</strong><span>错误/待优化</span></div>
      <div class="stat"><strong id="stReviewed">0</strong><span>已维护</span></div>
      <div class="stat"><strong id="stTraining">0</strong><span>进入训练集</span></div>
      <div class="stat"><strong id="stNoPred">0</strong><span>无预测</span></div>
    </section>
    <section class="workspace">
      <aside class="side">
        <div class="side-head">
          <div class="toolbar">
            <input id="search" placeholder="搜索文件名、识别结果、修正值">
            <div class="filters">
              <select id="filter">
                <option value="all">全部</option>
                <option value="error">仅错误</option>
                <option value="pending">待维护</option>
                <option value="reviewed">已维护</option>
                <option value="training">训练集</option>
              </select>
            </div>
          </div>
        </div>
        <div class="sample-list" id="sampleList"></div>
      </aside>
      <section class="detail">
        <section class="grid" id="grid"></section>
        <div class="empty" id="empty" hidden>没有符合条件的样本</div>
      </section>
    </section>
  </main>
  <div class="toast" id="toast"></div>
  <script>
    const state = { records: [], meta: {}, saving: false, activeFilename: null };
    const $ = (id) => document.getElementById(id);
    const statusText = { error: '错误', ok: '正确', pending: '待维护', no_prediction: '无预测' };

    function showToast(message) {
      const box = $('toast');
      box.textContent = message;
      box.style.display = 'block';
      clearTimeout(showToast.timer);
      showToast.timer = setTimeout(() => box.style.display = 'none', 2600);
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }

    function renderStats(summary) {
      $('stTotal').textContent = summary.total || 0;
      $('stErrors').textContent = summary.errors || 0;
      $('stReviewed').textContent = summary.reviewed || 0;
      $('stTraining').textContent = summary.training || 0;
      $('stNoPred').textContent = summary.no_prediction || 0;
    }

    function focusRecord(filename, scroll = true) {
      state.activeFilename = filename;
      render();
      if (!scroll) return;
      let item = document.querySelector(`.sample-item[data-filename="${CSS.escape(filename)}"]`);
      if (!item && $('filter').value !== 'all') {
        $('filter').value = 'all';
        render();
        item = document.querySelector(`.sample-item[data-filename="${CSS.escape(filename)}"]`);
      }
      if (item) {
        item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }

    function summarize(records) {
      return {
        total: records.length,
        errors: records.filter(r => r.status === 'error').length,
        reviewed: records.filter(r => r.reviewed).length,
        training: records.filter(r => r.use_for_training && r.corrected_label).length,
        no_prediction: records.filter(r => r.status === 'no_prediction').length,
      };
    }

    function currentRecords() {
      const filter = $('filter').value;
      const q = $('search').value.trim().toLowerCase();
      return state.records.map((row, index) => ({ ...row, _index: index })).filter(row => {
        if (filter === 'error' && row.status !== 'error') return false;
        if (filter === 'pending' && row.reviewed) return false;
        if (filter === 'reviewed' && !row.reviewed) return false;
        if (filter === 'training' && !(row.use_for_training && row.corrected_label)) return false;
        if (!q) return true;
        return [row.filename, row.prediction, row.label, row.corrected_label, row.notes].some(v => String(v || '').toLowerCase().includes(q));
      });
    }

    function renderList(rows) {
      $('sampleList').innerHTML = rows.map(row => {
        const badgeClass = row.status === 'error' ? 'error' : row.status === 'ok' ? 'ok' : 'pending';
        return `
          <button class="sample-item ${state.activeFilename === row.filename ? 'active' : ''}" data-filename="${escapeHtml(row.filename)}">
            <span class="sample-no">${row._index + 1}</span>
            <span class="sample-main">
              <span class="sample-file">${escapeHtml(row.filename)}</span>
              <span class="sample-code">${escapeHtml(row.prediction || '无')} -> ${escapeHtml(row.corrected_label || '未填')}</span>
            </span>
            <span class="badge ${badgeClass}">${row.reviewed ? (statusText[row.status] || row.status) : '未标注'}</span>
          </button>`;
      }).join('');
    }

    function renderDetail(row) {
      if (!row) {
        $('grid').innerHTML = '';
        return;
      }
      const badgeClass = row.status === 'error' ? 'error' : row.status === 'ok' ? 'ok' : 'pending';
      $('grid').innerHTML = `
        <article class="card ${badgeClass} active" data-filename="${escapeHtml(row.filename)}">
          <div class="top">
            <div class="file-wrap">
              <div class="file" title="${escapeHtml(row.filename)}">${row._index + 1}. ${escapeHtml(row.filename)}</div>
              <div class="review-state">${row.reviewed ? '已标注' : '未标注'} · ${row.use_for_training ? '进入训练' : '不进训练'}</div>
            </div>
            <div class="badge ${badgeClass}">${statusText[row.status] || row.status}</div>
          </div>
          <div class="image"><img src="${escapeHtml(row.image_url)}" alt="${escapeHtml(row.filename)}"></div>
          <div class="body">
            <label>识别结果<div class="readonly">${escapeHtml(row.prediction || row.prediction_error || '无')}</div></label>
            <label>原标签<div class="readonly">${escapeHtml(row.label || '未标注')}</div></label>
            <label>修正结果<input class="code js-code" maxlength="4" value="${escapeHtml(row.corrected_label || '')}"></label>
            <div class="checks">
              <label class="check"><input type="checkbox" class="js-error" ${row.is_error ? 'checked' : ''}>识别错误</label>
              <label class="check"><input type="checkbox" class="js-train" ${row.use_for_training ? 'checked' : ''}>用于优化</label>
            </div>
            <label>备注<textarea class="js-notes">${escapeHtml(row.notes || '')}</textarea></label>
            <div class="row-actions">
              <button class="js-prev">上一条</button>
              <button class="js-next">下一条</button>
              <button class="js-correct">标为正确</button>
              <button class="primary js-save">保存修正</button>
            </div>
          </div>
        </article>`;
    }

    function render() {
      renderStats(summarize(state.records));
      $('meta').textContent = `${state.meta.captcha_dir || ''} | 修正记录: ${state.meta.review_csv || ''}`;
      const rows = currentRecords();
      $('empty').hidden = rows.length > 0;
      if (rows.length && !rows.some(row => row.filename === state.activeFilename)) {
        state.activeFilename = rows[0].filename;
      }
      renderList(rows);
      const activeRow = rows.find(row => row.filename === state.activeFilename);
      renderDetail(activeRow);
    }

    async function loadSamples(refresh=false) {
      const url = refresh ? '/api/samples?refresh=1' : '/api/samples';
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      state.records = data.records || [];
      state.meta = data.meta || {};
      if (!state.activeFilename && state.records.length) {
        const firstTarget = state.records.find(row => !row.reviewed) || state.records.find(row => row.status === 'error') || state.records[0];
        state.activeFilename = firstTarget.filename;
      }
      render();
    }

    function collectCardPayload(card, markCorrect=false) {
      const filename = card.dataset.filename;
      const row = state.records.find(item => item.filename === filename);
      if (!row) return null;
      const codeInput = card.querySelector('.js-code');
      const errorInput = card.querySelector('.js-error');
      const trainInput = card.querySelector('.js-train');
      if (markCorrect) {
        codeInput.value = row.prediction || codeInput.value;
        errorInput.checked = false;
        trainInput.checked = Boolean(codeInput.value);
      }
      const payload = {
        filename,
        corrected_label: codeInput.value.trim(),
        is_error: errorInput.checked,
        use_for_training: trainInput.checked,
        reviewed: true,
        notes: card.querySelector('.js-notes').value.trim(),
      };
      return payload;
    }

    async function savePayload(payload) {
      const res = await fetch('/api/review', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const index = state.records.findIndex(item => item.filename === payload.filename);
      state.records[index] = data.record;
      state.activeFilename = payload.filename;
      return data.record;
    }

    async function saveCard(card, markCorrect=false) {
      const payload = collectCardPayload(card, markCorrect);
      if (!payload) return;
      await savePayload(payload);
      moveVisible(1);
      render();
      showToast('已保存');
    }

    function payloadFromRecord(row) {
      return {
        filename: row.filename,
        corrected_label: (row.corrected_label || row.label || row.prediction || '').trim(),
        is_error: Boolean(row.is_error),
        use_for_training: Boolean(row.use_for_training || row.corrected_label || row.label || row.prediction),
        reviewed: true,
        notes: row.notes || '',
      };
    }

    async function saveAllCards() {
      const cards = [...document.querySelectorAll('.card')];
      const payloads = new Map(state.records.map(row => [row.filename, payloadFromRecord(row)]));
      for (const card of cards) {
        const payload = collectCardPayload(card);
        if (payload) payloads.set(payload.filename, payload);
      }
      let saved = 0;
      for (const payload of payloads.values()) {
        await savePayload(payload);
        saved += 1;
      }
      render();
      return saved;
    }

    function moveVisible(step) {
      const rows = currentRecords();
      if (!rows.length) return;
      const current = rows.findIndex(row => row.filename === state.activeFilename);
      const next = current < 0 ? 0 : (current + step + rows.length) % rows.length;
      focusRecord(rows[next].filename, true);
    }

    document.addEventListener('click', async (event) => {
      const sampleBtn = event.target.closest('.sample-item');
      if (sampleBtn) {
        focusRecord(sampleBtn.dataset.filename, true);
        return;
      }
      if (event.target.closest('.js-prev')) {
        moveVisible(-1);
        return;
      }
      if (event.target.closest('.js-next')) {
        moveVisible(1);
        return;
      }
      const saveBtn = event.target.closest('.js-save');
      const correctBtn = event.target.closest('.js-correct');
      if (!saveBtn && !correctBtn) return;
      const card = event.target.closest('.card');
      try {
        await saveCard(card, Boolean(correctBtn));
      } catch (err) {
        showToast(err.message || String(err));
      }
    });
    $('search').addEventListener('input', render);
    $('filter').addEventListener('change', render);
    $('refreshBtn').addEventListener('click', async () => {
      $('refreshBtn').disabled = true;
      try {
        await loadSamples(true);
        showToast('已重新识别');
      } catch (err) {
        showToast(err.message || String(err));
      } finally {
        $('refreshBtn').disabled = false;
      }
    });
    document.addEventListener('input', (event) => {
      const card = event.target.closest?.('.card');
      if (!card) return;
      const filename = card.dataset.filename;
      const row = state.records.find(item => item.filename === filename);
      if (!row) return;
      if (event.target.classList.contains('js-code')) row.corrected_label = event.target.value.trim();
      if (event.target.classList.contains('js-notes')) row.notes = event.target.value;
    });
    document.addEventListener('change', (event) => {
      const card = event.target.closest?.('.card');
      if (!card) return;
      const filename = card.dataset.filename;
      const row = state.records.find(item => item.filename === filename);
      if (!row) return;
      if (event.target.classList.contains('js-error')) row.is_error = event.target.checked;
      if (event.target.classList.contains('js-train')) row.use_for_training = event.target.checked;
    });
    $('saveAllBtn').addEventListener('click', async () => {
      $('saveAllBtn').disabled = true;
      try {
        const saved = await saveAllCards();
        showToast(`已保存 ${saved} 条`);
      } catch (err) {
        showToast(err.message || String(err));
      } finally {
        $('saveAllBtn').disabled = false;
      }
    });
    $('exportBtn').addEventListener('click', async () => {
      $('exportBtn').disabled = true;
      try {
        await saveAllCards();
        const res = await fetch('/api/export-labels', {method: 'POST'});
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        showToast(`已导出 ${data.samples} 条训练标签: ${data.output}`);
      } catch (err) {
        showToast(err.message || String(err));
      } finally {
        $('exportBtn').disabled = false;
      }
    });
    loadSamples().catch(err => showToast(err.message || String(err)));
  </script>
</body>
</html>"""


def make_review_handler(config: dict):
    state = {"records": [], "meta": {}}

    def refresh_state() -> None:
        records, meta = build_review_records(
            captcha_dir=config["captcha_dir"],
            labels_path=config["labels_path"],
            model_path=config["model_path"],
            review_csv=config["review_csv"],
            device_name=config["device_name"],
        )
        state["records"] = records
        state["meta"] = meta

    def find_record(filename: str) -> Optional[dict]:
        for row in state["records"]:
            if row["filename"] == filename:
                return row
        return None

    def update_record(record: dict, review_row: dict) -> dict:
        updated = apply_review_row(record, review_row)
        for index, row in enumerate(state["records"]):
            if row["filename"] == record["filename"]:
                state["records"][index] = updated
                break
        state["meta"]["summary"] = summarize_review_records(state["records"])
        return updated

    refresh_state()

    class ReviewHandler(BaseHTTPRequestHandler):
        server_version = "CaptchaReview/1.0"

        def log_message(self, fmt: str, *args) -> None:
            print(f"[review] {self.address_string()} - {fmt % args}")

        def send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_text(self, text: str, status: int = 200) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = REVIEW_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/samples":
                query = parse_qs(parsed.query)
                if query.get("refresh", ["0"])[0] == "1":
                    refresh_state()
                self.send_json({"records": state["records"], "meta": state["meta"]})
                return
            if parsed.path.startswith("/captcha/"):
                filename = unquote(parsed.path.removeprefix("/captcha/"))
                if "/" in filename or "\\" in filename or not filename.endswith(".gif"):
                    self.send_text("非法文件名", status=400)
                    return
                image_path = config["captcha_dir"] / filename
                if not image_path.exists():
                    self.send_text("验证码不存在", status=404)
                    return
                body = image_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/gif")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_text("Not found", status=404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/review":
                length = int(self.headers.get("Content-Length", "0"))
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    filename = str(payload.get("filename") or "").strip()
                    record = find_record(filename)
                    if not record:
                        raise CaptchaError(f"未知样本: {filename}")
                    corrected = str(payload.get("corrected_label") or "").strip()
                    if corrected:
                        corrected = normalize_label(
                            corrected,
                            state["meta"]["charset"],
                            case_sensitive=bool(state["meta"].get("case_sensitive", False)),
                        )
                    use_for_training = bool(payload.get("use_for_training"))
                    if use_for_training and not corrected:
                        raise CaptchaError("用于优化的样本必须填写修正结果")
                    review_row = {
                        "filename": filename,
                        "prediction": record.get("prediction", ""),
                        "label": record.get("label", ""),
                        "corrected_label": corrected,
                        "is_error": bool(payload.get("is_error")),
                        "use_for_training": use_for_training,
                        "reviewed": bool(payload.get("reviewed", True)),
                        "notes": str(payload.get("notes") or "").strip(),
                        "updated_at": timestamp_now(),
                    }
                    rows = read_review_rows(config["review_csv"])
                    rows[filename] = review_row
                    write_review_rows(config["review_csv"], [rows[key] for key in sorted(rows)])
                    updated = update_record(record, review_row)
                    self.send_json({"record": updated, "summary": state["meta"]["summary"]})
                except Exception as exc:
                    self.send_text(str(exc), status=400)
                return
            if parsed.path == "/api/export-labels":
                try:
                    result = export_reviewed_labels(
                        captcha_dir=config["captcha_dir"],
                        labels_path=config["labels_path"],
                        review_csv=config["review_csv"],
                        output_path=config["reviewed_labels_path"],
                        charset=state["meta"]["charset"],
                        case_sensitive=bool(state["meta"].get("case_sensitive", False)),
                    )
                    self.send_json(result)
                except Exception as exc:
                    self.send_text(str(exc), status=400)
                return
            self.send_text("Not found", status=404)

    return ReviewHandler


def serve_review_page(
    *,
    captcha_dir: Path,
    labels_path: Path,
    model_path: Path,
    review_csv: Path,
    reviewed_labels_path: Path,
    device_name: str,
    host: str,
    port: int,
) -> None:
    handler = make_review_handler(
        {
            "captcha_dir": captcha_dir,
            "labels_path": labels_path,
            "model_path": model_path,
            "review_csv": review_csv,
            "reviewed_labels_path": reviewed_labels_path,
            "device_name": device_name,
        }
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"识别结果维护页: http://{host}:{port}/")
    print(f"修正记录: {review_csv}")
    print(f"导出训练集: {reviewed_labels_path}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止维护页")
    finally:
        httpd.server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="moxing GIF 验证码本地识别工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preprocess", help="将 GIF 融合成静态预处理 PNG")
    p.add_argument("--captcha-dir", default=str(DEFAULT_CAPTCHA_DIR))
    p.add_argument("--output-dir", default=str(DEFAULT_PREVIEW_DIR))
    p.add_argument(
        "--method",
        choices=("clean", "bestframe", "median", "darkest", "vote", "motion"),
        default=DEFAULT_METHOD,
    )
    p.add_argument("--binary", action="store_true")
    p.add_argument("--denoise", action="store_true")
    p.add_argument("--limit", type=int)

    p = sub.add_parser("compare", help="输出多种 GIF 融合方式的对比图")
    p.add_argument("--captcha-dir", default=str(DEFAULT_CAPTCHA_DIR))
    p.add_argument("--output", default=str(DEFAULT_COMPARE_SHEET))
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--binary", action="store_true")

    p = sub.add_parser("label-sheet", help="输出放大的验证码标注辅助图")
    p.add_argument("--captcha-dir", default=str(DEFAULT_CAPTCHA_DIR))
    p.add_argument("--output", default=str(SCRIPT_DIR / "captcha_label_sheet.png"))
    p.add_argument(
        "--method",
        choices=("clean", "bestframe", "median", "darkest", "vote", "motion"),
        default=DEFAULT_METHOD,
    )
    p.add_argument("--scale", type=int, default=3)
    p.add_argument("--columns", type=int, default=2)
    p.add_argument("--limit", type=int)

    p = sub.add_parser("init-labels", help="生成 labels.csv 标注模板")
    p.add_argument("--captcha-dir", default=str(DEFAULT_CAPTCHA_DIR))
    p.add_argument("--labels", default=str(DEFAULT_LABELS))
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("train", help="训练本地 CNN 模型")
    p.add_argument("--captcha-dir", default=str(DEFAULT_CAPTCHA_DIR))
    p.add_argument("--labels", default=str(DEFAULT_LABELS))
    p.add_argument("--model", default=str(DEFAULT_MODEL))
    p.add_argument("--charset", default=DEFAULT_CHARSET)
    p.add_argument("--case-sensitive", action="store_true")
    p.add_argument(
        "--method",
        choices=("clean", "bestframe", "median", "darkest", "vote", "motion"),
        default=DEFAULT_METHOD,
    )
    p.add_argument("--binary", action="store_true")
    p.add_argument("--denoise", action="store_true")
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--val-ratio", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--device", default="auto")

    p = sub.add_parser("predict", help="识别一个或多个验证码 GIF")
    p.add_argument("images", nargs="+")
    p.add_argument("--model", default=str(DEFAULT_MODEL))
    p.add_argument("--device", default="cpu")

    p = sub.add_parser("eval", help="用 labels.csv 评估模型并输出错误样本")
    p.add_argument("--captcha-dir", default=str(DEFAULT_CAPTCHA_DIR))
    p.add_argument("--labels", default=str(DEFAULT_LABELS))
    p.add_argument("--model", default=str(DEFAULT_MODEL))
    p.add_argument("--errors", default=str(DEFAULT_ERROR_CSV))
    p.add_argument("--device", default="cpu")

    p = sub.add_parser("review", help="启动本地页面维护识别结果和修正标签")
    p.add_argument("--captcha-dir", default=str(DEFAULT_CAPTCHA_DIR))
    p.add_argument("--labels", default=str(DEFAULT_LABELS))
    p.add_argument("--model", default=str(DEFAULT_MODEL))
    p.add_argument("--reviews", default=str(DEFAULT_REVIEW_CSV))
    p.add_argument("--reviewed-labels", default=str(DEFAULT_REVIEW_LABELS))
    p.add_argument("--device", default="cpu")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)

    p = sub.add_parser("export-reviewed-labels", help="将页面修正结果合并成训练标签 CSV")
    p.add_argument("--captcha-dir", default=str(DEFAULT_CAPTCHA_DIR))
    p.add_argument("--labels", default=str(DEFAULT_LABELS))
    p.add_argument("--model", default=str(DEFAULT_MODEL))
    p.add_argument("--reviews", default=str(DEFAULT_REVIEW_CSV))
    p.add_argument("--output", default=str(DEFAULT_REVIEW_LABELS))
    p.add_argument("--device", default="cpu")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "preprocess":
            preprocess_directory(
                Path(args.captcha_dir),
                Path(args.output_dir),
                method=args.method,
                binary=args.binary,
                denoise=args.denoise,
                limit=args.limit,
            )
        elif args.command == "init-labels":
            write_label_template(Path(args.captcha_dir), Path(args.labels), overwrite=args.overwrite)
        elif args.command == "compare":
            make_compare_sheet(
                Path(args.captcha_dir),
                Path(args.output),
                limit=args.limit,
                binary=args.binary,
            )
        elif args.command == "label-sheet":
            make_label_sheet(
                Path(args.captcha_dir),
                Path(args.output),
                method=args.method,
                scale=args.scale,
                columns=args.columns,
                limit=args.limit,
            )
        elif args.command == "train":
            train_model(
                captcha_dir=Path(args.captcha_dir),
                labels_path=Path(args.labels),
                model_path=Path(args.model),
                charset=args.charset,
                case_sensitive=args.case_sensitive,
                method=args.method,
                binary=args.binary,
                denoise=args.denoise,
                epochs=args.epochs,
                batch_size=args.batch_size,
                lr=args.lr,
                val_ratio=args.val_ratio,
                seed=args.seed,
                device_name=args.device,
            )
        elif args.command == "predict":
            predict_many(Path(args.model), [Path(path) for path in args.images], args.device)
        elif args.command == "eval":
            evaluate_checkpoint(
                model_path=Path(args.model),
                captcha_dir=Path(args.captcha_dir),
                labels_path=Path(args.labels),
                error_csv=Path(args.errors),
                device_name=args.device,
            )
        elif args.command == "review":
            serve_review_page(
                captcha_dir=Path(args.captcha_dir),
                labels_path=Path(args.labels),
                model_path=Path(args.model),
                review_csv=Path(args.reviews),
                reviewed_labels_path=Path(args.reviewed_labels),
                device_name=args.device,
                host=args.host,
                port=args.port,
            )
        elif args.command == "export-reviewed-labels":
            model_path = Path(args.model)
            charset = DEFAULT_CHARSET
            case_sensitive = False
            if model_path.exists():
                _, checkpoint, _ = load_checkpoint(model_path, args.device)
                charset = checkpoint["charset"]
                case_sensitive = bool(checkpoint.get("case_sensitive", False))
            result = export_reviewed_labels(
                captcha_dir=Path(args.captcha_dir),
                labels_path=Path(args.labels),
                review_csv=Path(args.reviews),
                output_path=Path(args.output),
                charset=charset,
                case_sensitive=case_sensitive,
            )
            print(f"已导出训练标签: {result['output']}，样本数: {result['samples']}，修正样本: {result['reviewed_samples']}")
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
