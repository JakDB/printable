from __future__ import annotations

import io
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageCms


ROOT = Path(__file__).resolve().parents[1]
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


def convert_to_cmyk_pdf(body: bytes, profile_key: str, page_width_mm: float, page_height_mm: float) -> bytes:
    profile = PROFILES.get(profile_key)
    if not profile:
        raise ValueError("Unknown CMYK profile")
    profile_path = profile["path"]
    if not profile_path.exists():
        raise FileNotFoundError(f"ICC profile not found: {profile_path}")

    with Image.open(io.BytesIO(body)) as image:
        source_icc = image.info.get("icc_profile")
        rgb = flatten_to_rgb(image)

    source_profile = (
        ImageCms.ImageCmsProfile(io.BytesIO(source_icc))
        if source_icc
        else ImageCms.createProfile("sRGB")
    )
    target_profile = ImageCms.ImageCmsProfile(str(profile_path))
    flags = ImageCms.Flags.BLACKPOINTCOMPENSATION
    cmyk = ImageCms.profileToProfile(
        rgb,
        source_profile,
        target_profile,
        renderingIntent=ImageCms.Intent.PERCEPTUAL,
        outputMode="CMYK",
        flags=flags,
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


class Handler(BaseHTTPRequestHandler):
    server_version = "ICCConvert/1.0"

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
            self.wfile.write(b'{"ok":true}')
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
            profile = params.get("profile", ["fogra51"])[0]
            page_width_mm = float(params.get("pageWidthMm", ["0"])[0])
            page_height_mm = float(params.get("pageHeightMm", ["0"])[0])
            if page_width_mm <= 0 or page_height_mm <= 0:
                raise ValueError("Invalid page size")

            body = self.rfile.read(length)
            pdf = convert_to_cmyk_pdf(body, profile, page_width_mm, page_height_mm)
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
