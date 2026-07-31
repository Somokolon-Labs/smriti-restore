"""Reference-based image quality metrics.

PSNR and SSIM are implemented directly rather than pulled from scikit-image, both
to keep the dependency list short and because the exact windowing matters when
numbers go on a model card. LPIPS uses a pretrained VGG16 as a perceptual feature
extractor, which correlates far better with human judgement than either.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("smriti.ml.metrics")


def _grey(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY).astype(np.float64)


def _match(reference: Image.Image, candidate: Image.Image) -> Image.Image:
    if candidate.size != reference.size:
        return candidate.resize(reference.size, Image.LANCZOS)
    return candidate


def psnr(reference: Image.Image, candidate: Image.Image) -> float:
    """Peak signal-to-noise ratio in dB. Higher is better; identical images are inf."""
    candidate = _match(reference, candidate)
    a = np.asarray(reference.convert("RGB"), dtype=np.float64)
    b = np.asarray(candidate.convert("RGB"), dtype=np.float64)
    mse = float(np.mean((a - b) ** 2))
    if mse <= 1e-10:
        return float("inf")
    return float(10.0 * np.log10((255.0**2) / mse))


def ssim(reference: Image.Image, candidate: Image.Image) -> float:
    """Structural similarity on luminance, Gaussian-windowed as in Wang et al. 2004."""
    candidate = _match(reference, candidate)
    x = _grey(reference)
    y = _grey(candidate)

    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    # 11x11 Gaussian, sigma 1.5, is the window the original paper specifies.
    kernel = (11, 11)
    sigma = 1.5

    mu_x = cv2.GaussianBlur(x, kernel, sigma)
    mu_y = cv2.GaussianBlur(y, kernel, sigma)
    mu_x_sq, mu_y_sq, mu_xy = mu_x**2, mu_y**2, mu_x * mu_y

    sigma_x = cv2.GaussianBlur(x * x, kernel, sigma) - mu_x_sq
    sigma_y = cv2.GaussianBlur(y * y, kernel, sigma) - mu_y_sq
    sigma_xy = cv2.GaussianBlur(x * y, kernel, sigma) - mu_xy

    numerator = (2 * mu_xy + c1) * (2 * sigma_xy + c2)
    denominator = (mu_x_sq + mu_y_sq + c1) * (sigma_x + sigma_y + c2)
    return float(np.mean(numerator / denominator))


class Lpips:
    """Perceptual distance via pretrained VGG16 features.

    Not the official LPIPS implementation, which needs calibrated linear weights.
    This is the same idea — normalised deep feature distance across several layers
    — and it is labelled as such on the model card rather than claiming to be the
    published metric. Directionally it behaves the same: lower is more similar.
    """

    def __init__(self) -> None:
        import torch
        from torchvision.models import VGG16_Weights, vgg16

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        weights = VGG16_Weights.IMAGENET1K_V1
        model = vgg16(weights=weights).features.eval().to(self.device)
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        self.model = model
        # Outputs of relu1_2, relu2_2, relu3_3, relu4_3.
        self.taps = {3, 8, 15, 22}
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device).view(1, 3, 1, 1)

    def _prepare(self, image: Image.Image, size: int = 512):
        picture = image.convert("RGB")
        picture.thumbnail((size, size), Image.LANCZOS)
        array = np.asarray(picture, dtype=np.float32) / 255.0
        tensor = self.torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0).to(self.device)
        return (tensor - self.mean) / self.std

    def distance(self, reference: Image.Image, candidate: Image.Image) -> float:
        candidate = _match(reference, candidate)
        with self.torch.no_grad():
            a = self._prepare(reference)
            b = self._prepare(candidate)
            if a.shape != b.shape:
                b = self.torch.nn.functional.interpolate(b, size=a.shape[-2:], mode="bilinear")

            total = 0.0
            for index, layer in enumerate(self.model):
                a, b = layer(a), layer(b)
                if index in self.taps:
                    # Unit-normalise channels so no single layer dominates.
                    a_n = a / (a.pow(2).sum(dim=1, keepdim=True).sqrt() + 1e-8)
                    b_n = b / (b.pow(2).sum(dim=1, keepdim=True).sqrt() + 1e-8)
                    total += float((a_n - b_n).pow(2).sum(dim=1).mean().item())
                if index >= max(self.taps):
                    break
        return total

    def unload(self) -> None:
        import gc

        self.model = None  # type: ignore[assignment]
        gc.collect()
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()


def safe_mean(values: list[float]) -> float:
    """Mean that ignores infinities, which PSNR produces for identical images."""
    finite = [v for v in values if np.isfinite(v)]
    return float(np.mean(finite)) if finite else float("nan")
