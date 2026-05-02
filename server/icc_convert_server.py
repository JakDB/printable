from __future__ import annotations

import io
import json
import os
import sys
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageCms, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
MM_PER_INCH = 25.4
CROP_LINE_MM = 0.25
PROFILES = {
    "fogra51": {
        "label": "FOGRA51 / PSO Coated v3",
        "path": ROOT / "public" / "icc" / "pso-coated_v3" / "PSOcoated_v3.icc",
    },
    "japan2011": {
        "label": "Japan Color 2011 Coated",
        "path": ROOT / "public" / "icc" / "JapanColor2011Coated" / "JapanColor2011Coated.icc",
    },
}
RENDERING_INTENTS = {
    "perceptual": ImageCms.Intent.PERCEPTUAL,
    "relative_colorimetric": ImageCms.Intent.RELATIVE_COLORIMETRIC,
}


def parse_float(value: str | None, label: str, *, minimum: float = 0) -> float:
    if value is None:
        raise ValueError(f"Missing {label}")
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {label}") from exc
    if parsed <= minimum:
        raise ValueError(f"Invalid {label}")
    return parsed


def parse_int(value: str | None, label: str, *, minimum: int = 0) -> int:
    if value is None:
        raise ValueError(f"Missing {label}")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {label}") from exc
    if parsed <= minimum:
        raise ValueError(f"Invalid {label}")
    return parsed


def pdf_bytes(value: str) -> bytes:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace")


def pdf_number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def build_cmyk_pdf(
    image_bytes: bytes,
    width: int,
    height: int,
    page_width_mm: float,
    page_height_mm: float,
    profile_label: str,
    icc_bytes: bytes,
) -> bytes:
    mm_per_inch = 25.4
    page_width_pt = page_width_mm / mm_per_inch * 72
    page_height_pt = page_height_mm / mm_per_inch * 72
    chunks: list[bytes] = []
    offsets = [0]
    position = 0

    def push(chunk: bytes | str) -> None:
        nonlocal position
        if isinstance(chunk, str):
            chunk = chunk.encode("latin-1", "replace")
        chunks.append(chunk)
        position += len(chunk)

    def obj(parts: list[bytes | str]) -> int:
        object_id = len(offsets)
        offsets.append(position)
        push(f"{object_id} 0 obj\n")
        for part in parts:
            push(part)
        push("\nendobj\n")
        return object_id

    push(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    obj(["<< /Type /Catalog /Pages 2 0 R /OutputIntents [6 0 R] >>"])
    obj(["<< /Type /Pages /Kids [3 0 R] /Count 1 >>"])
    obj(
        [
            "<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {pdf_number(page_width_pt)} {pdf_number(page_height_pt)}] "
            "/Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>"
        ]
    )
    obj(
        [
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace [/ICCBased 7 0 R] /BitsPerComponent 8 /Length {len(image_bytes)} >>\nstream\n",
            image_bytes,
            "\nendstream",
        ]
    )
    content = (
        "q\n"
        f"{pdf_number(page_width_pt)} 0 0 {pdf_number(page_height_pt)} 0 0 cm\n"
        "/Im1 Do\n"
        "Q\n"
    )
    obj([f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}endstream"])
    obj(
        [
            b"<< /Type /OutputIntent /S /GTS_PDFX /OutputConditionIdentifier (",
            pdf_bytes(profile_label),
            b") /Info (",
            pdf_bytes(profile_label),
            b") /DestOutputProfile 7 0 R >>",
        ]
    )
    obj([f"<< /N 4 /Alternate /DeviceCMYK /Length {len(icc_bytes)} >>\nstream\n", icc_bytes, "\nendstream"])

    xref_offset = position
    push(f"xref\n0 {len(offsets)}\n")
    push("0000000000 65535 f \n")
    for offset in offsets[1:]:
        push(f"{offset:010d} 00000 n \n")
    push(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF")

    return b"".join(chunks)


def flatten_to_rgb(image: Image.Image) -> Image.Image:
    image.load()
    if image.mode in ("RGBA", "LA") or ("transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return image.convert("RGB")


def resolve_profile_options(profile_key: str, rendering_intent_key: str) -> tuple[dict[str, object], int, Path]:
    profile = PROFILES.get(profile_key)
    if not profile:
        raise ValueError("Unknown CMYK profile")
    rendering_intent = RENDERING_INTENTS.get(rendering_intent_key)
    if rendering_intent is None:
        raise ValueError("Unknown rendering intent")
    profile_path = profile["path"]
    if not isinstance(profile_path, Path) or not profile_path.exists():
        raise FileNotFoundError(f"ICC profile not found: {profile_path}")
    return profile, rendering_intent, profile_path


def cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    source_ratio = image.width / image.height
    target_ratio = width / height
    left = 0.0
    top = 0.0
    right = float(image.width)
    bottom = float(image.height)

    if source_ratio > target_ratio:
        crop_width = image.height * target_ratio
        left = (image.width - crop_width) / 2
        right = left + crop_width
    else:
        crop_height = image.width / target_ratio
        top = (image.height - crop_height) / 2
        bottom = top + crop_height

    box = (
        max(0, round(left)),
        max(0, round(top)),
        min(image.width, round(right)),
        min(image.height, round(bottom)),
    )
    return image.crop(box).resize((width, height), Image.Resampling.LANCZOS)


def create_bleed_artwork(source: Image.Image, width: int, height: int, print_width_mm: float, print_height_mm: float, bleed_mm: float) -> Image.Image:
    page_width_mm = print_width_mm + bleed_mm * 2
    page_height_mm = print_height_mm + bleed_mm * 2
    bleed_x = max(1, round((bleed_mm / page_width_mm) * width))
    bleed_y = max(1, round((bleed_mm / page_height_mm) * height))
    trim_x = bleed_x
    trim_y = bleed_y
    trim_width = max(1, width - bleed_x * 2)
    trim_height = max(1, height - bleed_y * 2)

    artwork = Image.new("RGB", (width, height), "white")
    trim = cover_resize(source, trim_width, trim_height)
    artwork.paste(trim, (trim_x, trim_y))

    left = artwork.crop((trim_x, trim_y, trim_x + bleed_x, trim_y + trim_height))
    artwork.paste(ImageOps.mirror(left), (0, trim_y))

    right = artwork.crop((trim_x + trim_width - bleed_x, trim_y, trim_x + trim_width, trim_y + trim_height))
    artwork.paste(ImageOps.mirror(right), (trim_x + trim_width, trim_y))

    top = artwork.crop((0, trim_y, width, trim_y + bleed_y))
    artwork.paste(ImageOps.flip(top), (0, 0))

    bottom = artwork.crop((0, trim_y + trim_height - bleed_y, width, trim_y + trim_height))
    artwork.paste(ImageOps.flip(bottom), (0, trim_y + trim_height))

    artwork.paste(trim, (trim_x, trim_y))
    return artwork


def draw_crop_marks(sheet: Image.Image, scale: float, bleed_mm: float, crop_mark_mm: float) -> None:
    mark = max(1, round(crop_mark_mm * scale))
    bleed_px = max(1, round(bleed_mm * scale))
    line = max(1, round(CROP_LINE_MM * scale))
    half_line = round(line / 2)
    trim_left = mark + bleed_px
    trim_top = mark + bleed_px
    trim_right = sheet.width - mark - bleed_px
    trim_bottom = sheet.height - mark - bleed_px
    color = (38, 38, 38)
    draw = ImageDraw.Draw(sheet)

    draw.rectangle((0, trim_top - half_line, mark, trim_top - half_line + line - 1), fill=color)
    draw.rectangle((sheet.width - mark, trim_top - half_line, sheet.width, trim_top - half_line + line - 1), fill=color)
    draw.rectangle((0, trim_bottom - half_line, mark, trim_bottom - half_line + line - 1), fill=color)
    draw.rectangle((sheet.width - mark, trim_bottom - half_line, sheet.width, trim_bottom - half_line + line - 1), fill=color)
    draw.rectangle((trim_left - half_line, 0, trim_left - half_line + line - 1, mark), fill=color)
    draw.rectangle((trim_right - half_line, 0, trim_right - half_line + line - 1, mark), fill=color)
    draw.rectangle((trim_left - half_line, sheet.height - mark, trim_left - half_line + line - 1, sheet.height), fill=color)
    draw.rectangle((trim_right - half_line, sheet.height - mark, trim_right - half_line + line - 1, sheet.height), fill=color)


def create_print_sheet(
    source: Image.Image,
    print_width_mm: float,
    print_height_mm: float,
    dpi: int,
    bleed_mm: float,
    crop_mark_mm: float,
) -> tuple[Image.Image, float, float]:
    sheet_width_mm = print_width_mm + (bleed_mm + crop_mark_mm) * 2
    sheet_height_mm = print_height_mm + (bleed_mm + crop_mark_mm) * 2
    sheet_width = max(1, int((sheet_width_mm / MM_PER_INCH) * dpi + 0.999999))
    sheet_height = max(1, int((sheet_height_mm / MM_PER_INCH) * dpi + 0.999999))
    scale = sheet_width / sheet_width_mm
    mark_px = max(1, round(crop_mark_mm * scale))
    artwork_width = max(1, sheet_width - mark_px * 2)
    artwork_height = max(1, sheet_height - mark_px * 2)

    artwork = create_bleed_artwork(source, artwork_width, artwork_height, print_width_mm, print_height_mm, bleed_mm)
    sheet = Image.new("RGB", (sheet_width, sheet_height), "white")
    sheet.paste(artwork, (mark_px, mark_px))
    draw_crop_marks(sheet, scale, bleed_mm, crop_mark_mm)
    return sheet, sheet_width_mm, sheet_height_mm


def convert_to_cmyk_pdf(
    body: bytes,
    profile_key: str,
    print_width_mm: float,
    print_height_mm: float,
    dpi: int,
    bleed_mm: float,
    crop_mark_mm: float,
    rendering_intent_key: str = "perceptual",
) -> bytes:
    profile, rendering_intent, profile_path = resolve_profile_options(profile_key, rendering_intent_key)

    with Image.open(io.BytesIO(body)) as image:
        source_icc = image.info.get("icc_profile")
        image = ImageOps.exif_transpose(image)
        rgb = flatten_to_rgb(image)

    source_profile = (
        ImageCms.ImageCmsProfile(io.BytesIO(source_icc))
        if source_icc
        else ImageCms.createProfile("sRGB")
    )
    sheet, sheet_width_mm, sheet_height_mm = create_print_sheet(
        rgb,
        print_width_mm,
        print_height_mm,
        dpi,
        bleed_mm,
        crop_mark_mm,
    )
    target_profile = ImageCms.ImageCmsProfile(str(profile_path))
    flags = ImageCms.Flags.BLACKPOINTCOMPENSATION
    cmyk = ImageCms.profileToProfile(
        sheet,
        source_profile,
        target_profile,
        renderingIntent=rendering_intent,
        outputMode="CMYK",
        flags=flags,
    )
    if cmyk is None:
        raise RuntimeError("ICC transform failed")

    return build_cmyk_pdf(
        cmyk.tobytes(),
        cmyk.width,
        cmyk.height,
        sheet_width_mm,
        sheet_height_mm,
        str(profile["label"]),
        profile_path.read_bytes(),
    )


def convert_prepared_sheet_to_cmyk_pdf(
    body: bytes,
    profile_key: str,
    page_width_mm: float,
    page_height_mm: float,
    rendering_intent_key: str = "perceptual",
) -> bytes:
    profile, rendering_intent, profile_path = resolve_profile_options(profile_key, rendering_intent_key)

    with Image.open(io.BytesIO(body)) as image:
        source_icc = image.info.get("icc_profile")
        image = ImageOps.exif_transpose(image)
        rgb = flatten_to_rgb(image)

    source_profile = (
        ImageCms.ImageCmsProfile(io.BytesIO(source_icc))
        if source_icc
        else ImageCms.createProfile("sRGB")
    )
    target_profile = ImageCms.ImageCmsProfile(str(profile_path))
    cmyk = ImageCms.profileToProfile(
        rgb,
        source_profile,
        target_profile,
        renderingIntent=rendering_intent,
        outputMode="CMYK",
        flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
    )
    if cmyk is None:
        raise RuntimeError("ICC transform failed")

    return build_cmyk_pdf(
        cmyk.tobytes(),
        cmyk.width,
        cmyk.height,
        page_width_mm,
        page_height_mm,
        str(profile["label"]),
        profile_path.read_bytes(),
    )


def parse_multipart_form(content_type: str, body: bytes) -> tuple[dict[str, str], bytes]:
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + body
    )
    if not message.is_multipart():
        raise ValueError("Expected multipart form data")

    fields: dict[str, str] = {}
    image_bytes: bytes | None = None
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        if name == "image":
            image_bytes = payload
        elif name:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, "replace")

    if not image_bytes:
        raise ValueError("Missing image")
    return fields, image_bytes


class Handler(BaseHTTPRequestHandler):
    server_version = "ICCConvert/2.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "ok": True,
                        "version": "2.0",
                        "supportsOriginalImagePdf": True,
                    }
                ).encode("utf-8")
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/convert-cmyk-pdf":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("Empty request body")
            if length > 250 * 1024 * 1024:
                raise ValueError("Image is too large")

            params = parse_qs(parsed.query)
            content_type = self.headers.get("Content-Type", "")
            body = self.rfile.read(length)
            if content_type.startswith("multipart/form-data"):
                fields, image_body = parse_multipart_form(content_type, body)
                profile = fields.get("profile", "fogra51")
                print_width_mm = parse_float(fields.get("printWidthMm"), "print width")
                print_height_mm = parse_float(fields.get("printHeightMm"), "print height")
                dpi = parse_int(fields.get("dpi"), "DPI")
                bleed_mm = parse_float(fields.get("bleedMm"), "bleed", minimum=-0.000001)
                crop_mark_mm = parse_float(fields.get("cropMarkMm"), "crop mark", minimum=-0.000001)
                rendering_intent = fields.get("renderingIntent", "perceptual")
                pdf = convert_to_cmyk_pdf(
                    image_body,
                    profile,
                    print_width_mm,
                    print_height_mm,
                    dpi,
                    bleed_mm,
                    crop_mark_mm,
                    rendering_intent,
                )
            else:
                profile = params.get("profile", ["fogra51"])[0]
                page_width_mm = parse_float(params.get("pageWidthMm", ["0"])[0], "page width")
                page_height_mm = parse_float(params.get("pageHeightMm", ["0"])[0], "page height")
                rendering_intent = params.get("renderingIntent", ["perceptual"])[0]
                pdf = convert_prepared_sheet_to_cmyk_pdf(
                    body,
                    profile,
                    page_width_mm,
                    page_height_mm,
                    rendering_intent,
                )
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="printable-cmyk.pdf"')
            self.send_header("Content-Length", str(len(pdf)))
            self.end_headers()
            self.wfile.write(pdf)
        except Exception as exc:
            message = str(exc).encode("utf-8", "replace")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def main() -> None:
    host = os.environ.get("ICC_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("ICC_SERVER_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"ICC conversion server listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
