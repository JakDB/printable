from __future__ import annotations

import io
import math
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageCms, ImageChops, ImageDraw, ImageFont, ImageStat


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"F:\desktop\ChatGPT Image 2026年5月1日 17_35_53.png")
PROFILE_KEY = "fogra51"
PROFILE = ROOT / "public" / "icc" / "pso-coated_v3" / "PSOcoated_v3.icc"
API = "http://127.0.0.1:8787/api/convert-cmyk-pdf"
OUT_DIR = ROOT / "output" / "pdf"
TMP_DIR = ROOT / "tmp" / "pdfs"


def flatten_to_rgb(image: Image.Image) -> Image.Image:
    image.load()
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return image.convert("RGB")


def average_saturation(image: Image.Image) -> float:
    hsv = image.convert("HSV")
    return ImageStat.Stat(hsv.split()[1]).mean[0]


def average_luminance(image: Image.Image) -> float:
    y = image.convert("YCbCr").split()[0]
    return ImageStat.Stat(y).mean[0]


def rms_diff(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a, b)
    stat = ImageStat.Stat(diff)
    squares = sum(value**2 for value in stat.rms) / len(stat.rms)
    return math.sqrt(squares)


def percentile_diff(a: Image.Image, b: Image.Image, percentile: float) -> int:
    diff = ImageChops.difference(a, b).convert("L")
    hist = diff.histogram()
    threshold = diff.width * diff.height * percentile
    total = 0
    for value, count in enumerate(hist):
        total += count
        if total >= threshold:
            return value
    return 255


def make_side_by_side(original: Image.Image, proof: Image.Image, output: Path) -> None:
    max_height = 1000
    scale = min(1, max_height / original.height)
    size = (round(original.width * scale), round(original.height * scale))
    left = original.resize(size, Image.Resampling.LANCZOS)
    right = proof.resize(size, Image.Resampling.LANCZOS)
    gutter = 28
    label_h = 52
    canvas = Image.new("RGB", (size[0] * 2 + gutter, size[1] + label_h), (32, 32, 32))
    canvas.paste(left, (0, label_h))
    canvas.paste(right, (size[0] + gutter, label_h))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((16, 18), "Original RGB", fill=(255, 255, 255), font=font)
    draw.text((size[0] + gutter + 16, 18), "ICC CMYK -> sRGB soft proof", fill=(255, 255, 255), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=95)


def request_pdf(image: Image.Image, output: Path) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=98)
    params = urllib.parse.urlencode(
        {
            "profile": PROFILE_KEY,
            "pageWidthMm": "100",
            "pageHeightMm": str(100 * image.height / image.width),
        }
    )
    request = urllib.request.Request(
        f"{API}?{params}",
        data=buf.getvalue(),
        headers={"Content-Type": "image/jpeg"},
        method="POST",
    )
    pdf = urllib.request.urlopen(request, timeout=120).read()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pdf)
    return pdf


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE) as src:
        source_icc = src.info.get("icc_profile")
        original = flatten_to_rgb(src)

    source_profile = (
        ImageCms.ImageCmsProfile(io.BytesIO(source_icc))
        if source_icc
        else ImageCms.createProfile("sRGB")
    )
    cmyk_profile = ImageCms.ImageCmsProfile(str(PROFILE))
    flags = ImageCms.Flags.BLACKPOINTCOMPENSATION
    cmyk = ImageCms.profileToProfile(
        original,
        source_profile,
        cmyk_profile,
        renderingIntent=ImageCms.Intent.PERCEPTUAL,
        outputMode="CMYK",
        flags=flags,
    )
    proof = ImageCms.profileToProfile(
        cmyk,
        cmyk_profile,
        ImageCms.createProfile("sRGB"),
        renderingIntent=ImageCms.Intent.PERCEPTUAL,
        outputMode="RGB",
        flags=flags,
    )
    if cmyk is None or proof is None:
        raise RuntimeError("ICC transform failed")

    original_path = TMP_DIR / "hk_menu_original_rgb.jpg"
    proof_path = TMP_DIR / "hk_menu_fogra51_softproof.jpg"
    comparison_path = OUT_DIR / "hk_menu_fogra51_comparison.jpg"
    pdf_path = OUT_DIR / "hk_menu_fogra51_cmyk.pdf"

    original.save(original_path, quality=95)
    proof.save(proof_path, quality=95)
    make_side_by_side(original, proof, comparison_path)
    pdf = request_pdf(original, pdf_path)

    metrics = {
        "source": str(SOURCE),
        "profile": PROFILE_KEY,
        "size": f"{original.width}x{original.height}",
        "original_luminance": average_luminance(original),
        "proof_luminance": average_luminance(proof),
        "original_saturation": average_saturation(original),
        "proof_saturation": average_saturation(proof),
        "rms_rgb_diff": rms_diff(original, proof),
        "p95_luma_diff": percentile_diff(original, proof, 0.95),
        "pdf_size_bytes": len(pdf),
        "pdf_has_iccbased": b"/ICCBased" in pdf,
        "pdf_has_cmyk_profile": b"/N 4" in pdf,
        "original_preview": str(original_path),
        "softproof_preview": str(proof_path),
        "comparison": str(comparison_path),
        "pdf": str(pdf_path),
    }

    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"{key}: {value:.2f}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
