from __future__ import annotations

import io
import json
import os
import sys
import base64
import hashlib
import hmac
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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
APIXO_BASE_URL = os.environ.get("APIXO_BASE_URL", "https://api.apixo.ai").rstrip("/")
APIXO_MODEL = os.environ.get("APIXO_IMAGE_MODEL", "gpt-image-2")
APIXO_API_KEY = os.environ.get("APIXO_API_KEY", "")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT") or os.environ.get("S3_ENDPOINT", "")
MINIO_PUBLIC_URL = os.environ.get("MINIO_PUBLIC_URL", "").rstrip("/")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("S3_ACCESS_KEY_ID", "")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY") or os.environ.get("S3_SECRET_ACCESS_KEY", "")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET") or os.environ.get("S3_BUCKET", "")
MINIO_REGION = os.environ.get("MINIO_REGION") or os.environ.get("S3_REGION", "us-east-1")
MINIO_FORCE_PATH_STYLE = os.environ.get("S3_FORCE_PATH_STYLE", "true").lower() != "false"
MINIO_TEMP_IMAGE_TTL_SECONDS = int(os.environ.get("MINIO_TEMP_IMAGE_TTL_SECONDS", "3600"))


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


def contain_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    source_ratio = image.width / image.height
    target_ratio = width / height
    if source_ratio >= target_ratio:
        resized_width = width
        resized_height = max(1, round(width / source_ratio))
    else:
        resized_height = height
        resized_width = max(1, round(height * source_ratio))

    resized = image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
    artwork = Image.new("RGB", (width, height), "white")
    artwork.paste(resized, ((width - resized_width) // 2, (height - resized_height) // 2))
    return artwork


def create_bleed_artwork(
    source: Image.Image,
    width: int,
    height: int,
    print_width_mm: float,
    print_height_mm: float,
    bleed_mm: float,
    bleed_source: Image.Image | None = None,
) -> Image.Image:
    page_width_mm = print_width_mm + bleed_mm * 2
    page_height_mm = print_height_mm + bleed_mm * 2
    bleed_x = max(1, round((bleed_mm / page_width_mm) * width))
    bleed_y = max(1, round((bleed_mm / page_height_mm) * height))
    trim_x = bleed_x
    trim_y = bleed_y
    trim_width = max(1, width - bleed_x * 2)
    trim_height = max(1, height - bleed_y * 2)

    artwork = contain_resize(bleed_source, width, height) if bleed_source else cover_resize(source, width, height)
    if bleed_source:
        return artwork

    trim = cover_resize(source, trim_width, trim_height)
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
    bleed_source: Image.Image | None = None,
) -> tuple[Image.Image, float, float]:
    sheet_width_mm = print_width_mm + (bleed_mm + crop_mark_mm) * 2
    sheet_height_mm = print_height_mm + (bleed_mm + crop_mark_mm) * 2
    sheet_width = max(1, int((sheet_width_mm / MM_PER_INCH) * dpi + 0.999999))
    sheet_height = max(1, int((sheet_height_mm / MM_PER_INCH) * dpi + 0.999999))
    scale = sheet_width / sheet_width_mm
    mark_px = max(1, round(crop_mark_mm * scale))
    artwork_width = max(1, sheet_width - mark_px * 2)
    artwork_height = max(1, sheet_height - mark_px * 2)

    artwork = create_bleed_artwork(source, artwork_width, artwork_height, print_width_mm, print_height_mm, bleed_mm, bleed_source)
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
    bleed_body: bytes | None = None,
) -> bytes:
    profile, rendering_intent, profile_path = resolve_profile_options(profile_key, rendering_intent_key)

    with Image.open(io.BytesIO(body)) as image:
        source_icc = image.info.get("icc_profile")
        image = ImageOps.exif_transpose(image)
        rgb = flatten_to_rgb(image)

    bleed_rgb = None
    if bleed_body:
        with Image.open(io.BytesIO(bleed_body)) as bleed_image:
            bleed_image = ImageOps.exif_transpose(bleed_image)
            bleed_rgb = flatten_to_rgb(bleed_image)

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
        bleed_rgb,
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


def parse_multipart_form(content_type: str, body: bytes) -> tuple[dict[str, str], bytes, bytes | None]:
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + body
    )
    if not message.is_multipart():
        raise ValueError("Expected multipart form data")

    fields: dict[str, str] = {}
    image_bytes: bytes | None = None
    bleed_image_bytes: bytes | None = None
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        if name == "image":
            image_bytes = payload
        elif name == "bleedImage":
            bleed_image_bytes = payload
        elif name:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, "replace")

    if not image_bytes:
        raise ValueError("Missing image")
    return fields, image_bytes, bleed_image_bytes


def read_json_body(handler: BaseHTTPRequestHandler, *, limit_mb: int = 50) -> dict[str, object]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        raise ValueError("Empty request body")
    if length > limit_mb * 1024 * 1024:
        raise ValueError("Request body is too large")
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON request body") from exc
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    return data


def apixo_request(path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    if not APIXO_API_KEY:
        raise RuntimeError("Missing APIXO_API_KEY")

    command = [
        "curl",
        "-sS",
        "--fail-with-body",
        "-H",
        f"Authorization: Bearer {APIXO_API_KEY}",
    ]
    if payload is not None:
        command.extend([
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps(payload),
        ])
    command.append(f"{APIXO_BASE_URL}{path}")

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("APIXO request timed out") from exc
    if result.returncode != 0:
        detail = result.stdout.strip() or result.stderr.strip()
        raise RuntimeError(f"APIXO request failed: {detail}")

    response_body = result.stdout.encode("utf-8")
    try:
        decoded = json.loads(response_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("APIXO returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("APIXO returned unexpected response")
    return decoded


def parse_image_data_url(image_data_url: str) -> tuple[bytes, str, str]:
    if not image_data_url.startswith("data:image/"):
        raise ValueError("Missing source image")

    header, _, encoded = image_data_url.partition(",")
    if not encoded or ";base64" not in header:
        raise ValueError("Expected base64 image data URL")

    content_type = header[5:].split(";")[0]
    extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type, "png")
    try:
        body = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("Invalid base64 image data") from exc
    if not body:
        raise ValueError("Empty image data")
    return body, content_type, extension


def aws_signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    date_key = hmac.new(("AWS4" + secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode("utf-8"), hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def s3_encode_key(key: str) -> str:
    return "/".join(quote(part, safe="") for part in key.split("/"))


def build_minio_request(method: str, bucket: str, key: str, body: bytes, content_type: str, query: str = "") -> Request:
    if not all([MINIO_ENDPOINT, MINIO_PUBLIC_URL, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET]):
        raise RuntimeError("Missing MinIO environment configuration")

    endpoint = MINIO_ENDPOINT.rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError("Invalid MinIO endpoint")

    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    encoded_key = s3_encode_key(key)
    payload_hash = hashlib.sha256(body).hexdigest()

    if MINIO_FORCE_PATH_STYLE:
        host = parsed.netloc
        canonical_uri = f"/{quote(bucket, safe='')}"
        if encoded_key:
            canonical_uri += f"/{encoded_key}"
        upload_url = f"{parsed.scheme}://{host}{canonical_uri}"
    else:
        host = f"{bucket}.{parsed.netloc}"
        canonical_uri = f"/{encoded_key}" if encoded_key else "/"
        upload_url = f"{parsed.scheme}://{host}{canonical_uri}"
    canonical_query = query
    if query:
        upload_url = f"{upload_url}?{query}"

    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join([
        method,
        canonical_uri,
        canonical_query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])
    credential_scope = f"{date_stamp}/{MINIO_REGION}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(
        aws_signing_key(MINIO_SECRET_KEY, date_stamp, MINIO_REGION),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        "AWS4-HMAC-SHA256 "
        f"Credential={MINIO_ACCESS_KEY}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    return Request(
        upload_url,
        data=body,
        headers={
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": host,
            "X-Amz-Content-Sha256": payload_hash,
            "X-Amz-Date": amz_date,
        },
        method=method,
    )


def ensure_minio_bucket() -> None:
    request = build_minio_request("PUT", MINIO_BUCKET, "", b"", "application/octet-stream")
    try:
        with urlopen(request, timeout=60):
            return
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 409 and ("BucketAlready" in detail or "BucketAlreadyOwnedByYou" in detail):
            return
        raise RuntimeError(f"MinIO bucket check failed with status {exc.code}: {detail}") from exc


def ensure_minio_bucket_public() -> None:
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{MINIO_BUCKET}/*"],
            }
        ],
    }
    body = json.dumps(policy, separators=(",", ":")).encode("utf-8")
    request = build_minio_request("PUT", MINIO_BUCKET, "", body, "application/json", "policy=")
    try:
        with urlopen(request, timeout=60):
            return
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"MinIO public policy failed with status {exc.code}: {detail}") from exc


def minio_public_object_url(base_url: str, key: str) -> str:
    return f"{base_url.rstrip('/')}/{quote(MINIO_BUCKET, safe='')}/{s3_encode_key(key)}"


def minio_endpoint_public_url(key: str) -> str:
    endpoint = MINIO_ENDPOINT.rstrip("/")
    parsed = urlparse(endpoint)
    if MINIO_FORCE_PATH_STYLE:
        return minio_public_object_url(endpoint, key)
    return f"{parsed.scheme}://{MINIO_BUCKET}.{parsed.netloc}/{s3_encode_key(key)}"


def is_public_image_url(url: str) -> bool:
    try:
        request = Request(url, method="HEAD")
        with urlopen(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.status < 400 and content_type.startswith("image/")
    except Exception:
        return False


def delete_minio_object(key: str) -> None:
    request = build_minio_request("DELETE", MINIO_BUCKET, key, b"", "application/octet-stream")
    try:
        with urlopen(request, timeout=60) as response:
            if response.status >= 300:
                raise RuntimeError(f"MinIO delete failed with status {response.status}")
    except HTTPError as exc:
        if exc.code == 404:
            return
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"MinIO delete failed with status {exc.code}: {detail}") from exc


def schedule_minio_delete(key: str) -> None:
    if MINIO_TEMP_IMAGE_TTL_SECONDS <= 0:
        return

    def delete_later() -> None:
        try:
            delete_minio_object(key)
            sys.stderr.write(f"Deleted temporary MinIO image after TTL: {key}\n")
        except Exception as exc:
            sys.stderr.write(f"Failed to delete temporary MinIO image {key}: {exc}\n")

    timer = threading.Timer(MINIO_TEMP_IMAGE_TTL_SECONDS, delete_later)
    timer.daemon = True
    timer.start()


def upload_to_minio(body: bytes, content_type: str, extension: str) -> str:
    now = datetime.now(timezone.utc)
    key = f"upscale/{now.strftime('%Y%m%d')}/{uuid.uuid4().hex}.{extension}"
    ensure_minio_bucket()
    ensure_minio_bucket_public()

    request = build_minio_request("PUT", MINIO_BUCKET, key, body, content_type)
    try:
        with urlopen(request, timeout=60) as response:
            if response.status >= 300:
                raise RuntimeError(f"MinIO upload failed with status {response.status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"MinIO upload failed with status {exc.code}: {detail}") from exc

    schedule_minio_delete(key)

    configured_url = minio_public_object_url(MINIO_PUBLIC_URL, key)
    if is_public_image_url(configured_url):
        return configured_url

    fallback_url = minio_endpoint_public_url(key)
    if is_public_image_url(fallback_url):
        return fallback_url

    return configured_url


def start_apixo_upscale(
    image_data_url: str,
    resolution: str,
    prompt: str | None = None,
    aspect_ratio: str | None = None,
) -> dict[str, object]:
    if resolution not in ("2k", "4k"):
        raise ValueError("Resolution must be 2k or 4k")

    resolution_label = resolution.upper()
    image_body, content_type, extension = parse_image_data_url(image_data_url)
    image_url = upload_to_minio(image_body, content_type, extension)
    supported_aspect_ratios = {"auto", "1:1", "3:4", "4:3", "9:16", "16:9"}
    if aspect_ratio not in supported_aspect_ratios:
        aspect_ratio = "auto"
    fallback_prompt = " ".join(
        [
            f"将当前图片分辨度提升到 {resolution_label}。",
            "不要扩图，保持原图比例生图。",
            "必须保持原图完整画面、原图边界、原图裁切范围、原图构图和主体位置完全不变。",
            "不要横向拉伸，不要纵向拉伸，不要压扁人物，不要改变人物比例。",
            "不要向左、右、上、下增加任何新内容，不要添加边框、白边、背景或画布外延。",
            "只提升细节、锐度、质感和印刷分辨率。",
        ]
    )
    payload = {
        "request_type": "async",
        "provider": "auto",
        "input": {
            "mode": "image-to-image",
            "prompt": prompt or fallback_prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "image_urls": [image_url],
        },
    }
    return apixo_request(f"/api/v1/generateTask/{APIXO_MODEL}", payload)


def get_apixo_status(task_id: str) -> dict[str, object]:
    if not task_id:
        raise ValueError("Missing taskId")
    return apixo_request(f"/api/v1/statusTask/{APIXO_MODEL}?taskId={task_id}")


def fetch_remote_image(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Only HTTPS image URLs are supported")

    request = Request(url, headers={"User-Agent": "Printable/1.0"})
    with urlopen(request, timeout=60) as response:
        content_type = response.headers.get("Content-Type", "image/png").split(";")[0]
        if not content_type.startswith("image/"):
            raise ValueError("Remote URL did not return an image")
        return response.read(), content_type


class Handler(BaseHTTPRequestHandler):
    server_version = "ICCConvert/2.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "ok": True,
                        "version": "2.0",
                        "supportsOriginalImagePdf": True,
                        "supportsImageUpscale": True,
                    }
                ).encode("utf-8")
            )
            return

        if parsed.path == "/api/upscale-status":
            try:
                params = parse_qs(parsed.query)
                task_id = params.get("taskId", [""])[0]
                payload = json.dumps(get_apixo_status(task_id)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                message = str(exc).encode("utf-8", "replace")
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)
            return

        if parsed.path == "/api/proxy-image":
            try:
                params = parse_qs(parsed.query)
                url = params.get("url", [""])[0]
                image, content_type = fetch_remote_image(url)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(image)))
                self.end_headers()
                self.wfile.write(image)
            except Exception as exc:
                message = str(exc).encode("utf-8", "replace")
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/upscale-image":
            try:
                data = read_json_body(self)
                image_data_url = data.get("imageDataUrl")
                resolution = data.get("resolution")
                prompt = data.get("prompt")
                aspect_ratio = data.get("aspectRatio")
                if not isinstance(image_data_url, str):
                    raise ValueError("Missing imageDataUrl")
                if not isinstance(resolution, str):
                    raise ValueError("Missing resolution")
                if prompt is not None and not isinstance(prompt, str):
                    raise ValueError("Invalid prompt")
                if aspect_ratio is not None and not isinstance(aspect_ratio, str):
                    raise ValueError("Invalid aspectRatio")
                payload = json.dumps(start_apixo_upscale(image_data_url, resolution, prompt, aspect_ratio)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                message = str(exc).encode("utf-8", "replace")
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)
            return

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
                fields, image_body, bleed_image_body = parse_multipart_form(content_type, body)
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
                    bleed_image_body,
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
