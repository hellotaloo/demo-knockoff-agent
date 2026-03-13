"""
Generate mock document images for demo purposes.

Creates two sets of documents per document type:
- VALID set: Agent should always accept these
- INVALID set: Agent should always decline these

Usage:
    python scripts/generate_demo_documents.py
"""

import qrcode
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Config ──────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "demo_documents"

# Main document types (slug, Dutch name, category label, requires_back)
DOCUMENT_TYPES = [
    ("id_card", "ID-kaart", "Identiteitsdocument", True),
    ("passport", "Paspoort", "Identiteitsdocument", False),
    ("driver_license", "Rijbewijs", "Certificaat", False),
    ("work_permit", "Arbeidsvergunning", "Certificaat", False),
    ("medical_cert", "Medisch attest", "Certificaat", False),
    ("bank_details", "Bankgegevens", "Financieel", False),
    ("diploma", "Diploma / Certificaat", "Certificaat", False),
]

# Color palette
COLORS = {
    "valid": {
        "bg": (245, 248, 250),         # Light cool gray
        "header_bg": (220, 235, 225),   # Soft sage green
        "accent": (90, 160, 110),       # Muted green
        "text": (50, 55, 60),           # Dark gray
        "subtitle": (120, 130, 140),    # Medium gray
        "border": (200, 210, 215),      # Light border
        "badge_bg": (220, 240, 225),    # Green tint
        "badge_text": (60, 130, 80),    # Green text
        "qr_fill": (70, 140, 90),       # Green QR
    },
    "invalid": {
        "bg": (250, 246, 245),          # Warm light gray
        "header_bg": (240, 220, 220),   # Soft rose
        "accent": (180, 90, 90),        # Muted red
        "text": (50, 55, 60),
        "subtitle": (120, 130, 140),
        "border": (215, 200, 200),
        "badge_bg": (245, 220, 220),
        "badge_text": (160, 60, 60),
        "qr_fill": (160, 70, 70),       # Red QR
    },
}

# Fake data for document fields
FAKE_DATA = {
    "id_card": {
        "fields": [
            ("Naam / Name", "De Vries"),
            ("Voornaam / Prenom", "Pieter"),
            ("Geboortedatum", "15.03.1992"),
            ("Nationaliteit", "Belg"),
            ("Kaartnummer", "592-1234567-85"),
            ("Geldig tot", "15.03.2029"),
        ],
        "fields_back": [
            ("Rijksregisternummer", "92.03.15-123.45"),
            ("Adres", "Kerkstraat 42"),
            ("Gemeente", "2000 Antwerpen"),
            ("Uitgegeven te", "Antwerpen"),
            ("Uitgiftedatum", "20.01.2024"),
        ],
    },
    "passport": {
        "fields": [
            ("Naam / Surname", "De Vries"),
            ("Voornaam / Given names", "Pieter Jan"),
            ("Nationaliteit", "BELG / BELGIAN"),
            ("Geboortedatum", "15 MAR 1992"),
            ("Geboorteplaats", "ANTWERPEN"),
            ("Paspoortnummer", "EH 123456"),
            ("Datum afgifte", "20 JAN 2024"),
            ("Geldig tot", "20 JAN 2034"),
        ],
    },
    "driver_license": {
        "fields": [
            ("Naam", "De Vries"),
            ("Voornaam", "Pieter"),
            ("Geboortedatum", "15.03.1992"),
            ("Rijbewijsnummer", "0912345678"),
            ("Categorieen", "B, BE"),
            ("Geldig van", "01.06.2015"),
            ("Geldig tot", "01.06.2030"),
        ],
    },
    "work_permit": {
        "fields": [
            ("Naam", "De Vries"),
            ("Voornaam", "Pieter"),
            ("Nationaliteit", "EU-burger"),
            ("Type vergunning", "Arbeidskaart B"),
            ("Werkgever", "Taloo NV"),
            ("Geldig van", "01.01.2025"),
            ("Geldig tot", "31.12.2025"),
            ("Regio", "Vlaanderen"),
        ],
    },
    "medical_cert": {
        "fields": [
            ("Patient", "De Vries, Pieter"),
            ("Geboortedatum", "15.03.1992"),
            ("Arts", "Dr. J. Peeters"),
            ("Datum onderzoek", "10.03.2026"),
            ("Conclusie", "Geschikt"),
            ("Geldig tot", "10.03.2027"),
            ("Referentie", "MED-2026-04521"),
        ],
    },
    "bank_details": {
        "fields": [
            ("Rekeninghouder", "Pieter De Vries"),
            ("IBAN", "BE68 5390 0754 7034"),
            ("BIC", "TRIOBEBB"),
            ("Bank", "Triodos Bank"),
            ("Type rekening", "Zichtrekening"),
        ],
    },
    "diploma": {
        "fields": [
            ("Naam", "De Vries, Pieter Jan"),
            ("Geboortedatum", "15 maart 1992"),
            ("Opleiding", "Elektromechanica"),
            ("Niveau", "Secundair onderwijs (TSO)"),
            ("Instelling", "GO! Atheneum Antwerpen"),
            ("Academiejaar", "2009 - 2010"),
            ("Behaald op", "30 juni 2010"),
        ],
    },
}

# Invalid reasons (shown as stamp / watermark)
INVALID_REASONS = {
    "id_card": "VERLOPEN / EXPIRED",
    "passport": "VERLOPEN / EXPIRED",
    "driver_license": "ONLEESBAAR / ILLEGIBLE",
    "work_permit": "ONGELDIG / INVALID",
    "medical_cert": "VERLOPEN / EXPIRED",
    "bank_details": "ONVOLLEDIG / INCOMPLETE",
    "diploma": "ONLEESBAAR / ILLEGIBLE",
}


# ── Drawing helpers ─────────────────────────────────────────────────────────


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a system font. Falls back to default if not found."""
    font_paths = [
        # macOS
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/Library/Fonts/Arial.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    bold_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    paths = bold_paths if bold else font_paths
    for path in paths:
        try:
            return ImageFont.truetype(path, size, index=1 if bold and "ttc" in path else 0)
        except (OSError, IndexError):
            continue
    return ImageFont.load_default()


def draw_taloo_logo(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color: tuple):
    """Draw the Taloo text logo with a simple geometric mark."""
    font = get_font(size, bold=True)
    draw.text((x, y), "taloo", fill=color, font=font)

    # Small diamond mark before text
    diamond_size = size // 4
    dx, dy = x - diamond_size - 8, y + size // 2
    draw.polygon([
        (dx, dy - diamond_size),
        (dx + diamond_size, dy),
        (dx, dy + diamond_size),
        (dx - diamond_size, dy),
    ], fill=color)


def make_qr_code(data: str, fill_color: tuple, size: int = 120) -> Image.Image:
    """Generate a QR code image."""
    qr = qrcode.QRCode(version=1, box_size=4, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill_color, back_color=(255, 255, 255, 0))
    img = img.convert("RGBA")

    # Make white pixels transparent
    pixels = img.load()
    for i in range(img.width):
        for j in range(img.height):
            if pixels[i, j][:3] == (255, 255, 255):
                pixels[i, j] = (255, 255, 255, 0)

    return img.resize((size, size), Image.LANCZOS)


def draw_rounded_rect(draw: ImageDraw.ImageDraw, xy: tuple, radius: int, fill: tuple, outline: tuple = None):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline)


def draw_diagonal_stamp(img: Image.Image, text: str, color: tuple):
    """Draw a diagonal watermark stamp across the image."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font = get_font(36, bold=True)
    stamp_color = (*color, 100)  # Semi-transparent

    # Draw rotated text as a stamp
    text_img = Image.new("RGBA", (500, 60), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_img)
    text_draw.text((10, 5), text, fill=stamp_color, font=font)

    # Draw border around stamp
    bbox = text_draw.textbbox((10, 5), text, font=font)
    border_color = (*color, 80)
    text_draw.rectangle(
        (bbox[0] - 8, bbox[1] - 5, bbox[2] + 8, bbox[3] + 5),
        outline=border_color, width=3
    )

    rotated = text_img.rotate(25, expand=True, resample=Image.BICUBIC)
    # Center the stamp
    paste_x = (img.width - rotated.width) // 2
    paste_y = (img.height - rotated.height) // 2

    img.paste(rotated, (paste_x, paste_y), rotated)


# ── Document generator ──────────────────────────────────────────────────────


def generate_document(
    slug: str,
    name: str,
    category: str,
    variant: str,  # "valid" or "invalid"
    side: str = "front",  # "front" or "back"
) -> Image.Image:
    """Generate a single mock document image."""
    width, height = 800, 1060
    colors = COLORS[variant]

    img = Image.new("RGBA", (width, height), colors["bg"])
    draw = ImageDraw.Draw(img)

    y_cursor = 0

    # ── Header bar ──────────────────────────────────────────────────────
    header_h = 140
    draw_rounded_rect(draw, (0, 0, width, header_h), radius=0, fill=colors["header_bg"])

    # Taloo logo top-left
    draw_taloo_logo(draw, 80, 20, 28, colors["accent"])

    # Category label
    cat_font = get_font(13)
    draw.text((60, 58), category.upper(), fill=colors["subtitle"], font=cat_font)

    # Document title
    title_font = get_font(26, bold=True)
    side_label = " (Achterkant)" if side == "back" else ""
    draw.text((60, 78), f"{name}{side_label}", fill=colors["text"], font=title_font)

    # Status badge top-right
    badge_font = get_font(14, bold=True)
    badge_text = "DEMO — GELDIG" if variant == "valid" else "DEMO — ONGELDIG"
    badge_w = 180
    badge_x = width - badge_w - 30
    badge_y = 55
    draw_rounded_rect(
        draw,
        (badge_x, badge_y, badge_x + badge_w, badge_y + 32),
        radius=16,
        fill=colors["badge_bg"],
    )
    # Center badge text
    text_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    text_w = text_bbox[2] - text_bbox[0]
    draw.text(
        (badge_x + (badge_w - text_w) // 2, badge_y + 7),
        badge_text,
        fill=colors["badge_text"],
        font=badge_font,
    )

    y_cursor = header_h + 30

    # ── Separator line ──────────────────────────────────────────────────
    draw.line([(40, y_cursor), (width - 40, y_cursor)], fill=colors["border"], width=1)
    y_cursor += 25

    # ── QR Code + instruction block ────────────────────────────────────
    qr_data = f"taloo:demo:{variant}:{slug}:{side}"
    qr_img = make_qr_code(qr_data, colors["qr_fill"], size=130)
    img.paste(qr_img, (60, y_cursor), qr_img)

    # Instruction text next to QR
    inst_font = get_font(13)
    inst_x = 210
    inst_lines = [
        "DEMO DOCUMENT — NIET ECHT",
        "",
        f"Type: {name}",
        f"Variant: {'Geldig (accepteren)' if variant == 'valid' else 'Ongeldig (weigeren)'}",
        f"Zijde: {'Voorkant' if side == 'front' else 'Achterkant'}",
        "",
        "Scan QR-code voor metadata.",
        "Dit document is uitsluitend",
        "bedoeld voor demodoeleinden.",
    ]
    for i, line in enumerate(inst_lines):
        color = colors["accent"] if i == 0 else colors["subtitle"]
        font = get_font(13, bold=True) if i == 0 else inst_font
        draw.text((inst_x, y_cursor + i * 20), line, fill=color, font=font)

    y_cursor += 160

    # ── Document fields ─────────────────────────────────────────────────
    draw.line([(40, y_cursor), (width - 40, y_cursor)], fill=colors["border"], width=1)
    y_cursor += 20

    field_key = slug
    data = FAKE_DATA.get(field_key, {})
    fields = data.get(f"fields_{side}", data.get("fields", []))

    label_font = get_font(13)
    value_font = get_font(17, bold=True)

    for label, value in fields:
        # Field label
        draw.text((60, y_cursor), label, fill=colors["subtitle"], font=label_font)
        y_cursor += 18

        # Field value
        if variant == "invalid" and slug == "bank_details" and label == "IBAN":
            value = "BE68 **** **** ****"  # Incomplete for invalid variant

        draw.text((60, y_cursor), value, fill=colors["text"], font=value_font)
        y_cursor += 32

        # Separator
        draw.line([(60, y_cursor), (width - 60, y_cursor)], fill=(*colors["border"], 120), width=1)
        y_cursor += 14

    # ── Photo placeholder (for identity docs) ──────────────────────────
    if slug in ("id_card", "passport", "driver_license") and side == "front":
        photo_x = width - 200
        photo_y = header_h + 200
        photo_w, photo_h = 140, 170
        draw_rounded_rect(
            draw,
            (photo_x, photo_y, photo_x + photo_w, photo_y + photo_h),
            radius=8,
            fill=(*colors["border"], 180),
            outline=colors["accent"],
        )
        # Photo placeholder icon
        photo_font = get_font(11)
        draw.text((photo_x + 42, photo_y + 65), "FOTO", fill=colors["subtitle"], font=photo_font)
        draw.text((photo_x + 22, photo_y + 82), "PLACEHOLDER", fill=colors["subtitle"], font=photo_font)

    # ── Footer ──────────────────────────────────────────────────────────
    footer_y = height - 80
    draw.line([(40, footer_y), (width - 40, footer_y)], fill=colors["border"], width=1)

    footer_font = get_font(11)
    draw.text(
        (60, footer_y + 15),
        "Dit is een demo-document gegenereerd door Taloo.",
        fill=colors["subtitle"],
        font=footer_font,
    )
    draw.text(
        (60, footer_y + 32),
        "Niet geldig als officieel document. Uitsluitend voor demonstratiedoeleinden.",
        fill=colors["subtitle"],
        font=footer_font,
    )

    ref_font = get_font(10)
    ref_text = f"REF: TALOO-DEMO-{slug.upper()}-{variant.upper()}-{side.upper()}"
    draw.text((60, footer_y + 52), ref_text, fill=(*colors["subtitle"], 150), font=ref_font)

    # ── Invalid stamp overlay ───────────────────────────────────────────
    if variant == "invalid":
        reason = INVALID_REASONS.get(slug, "ONGELDIG / INVALID")
        draw_diagonal_stamp(img, reason, colors["accent"])

    return img


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    valid_dir = OUTPUT_DIR / "valid"
    invalid_dir = OUTPUT_DIR / "invalid"
    valid_dir.mkdir(exist_ok=True)
    invalid_dir.mkdir(exist_ok=True)

    total = 0
    for slug, name, category, has_back in DOCUMENT_TYPES:
        for variant in ("valid", "invalid"):
            out_dir = valid_dir if variant == "valid" else invalid_dir

            # Front side
            img = generate_document(slug, name, category, variant, "front")
            path = out_dir / f"{slug}_front.png"
            img.save(path, "PNG")
            print(f"  Created: {path.relative_to(OUTPUT_DIR)}")
            total += 1

            # Back side (only for id_card)
            if has_back:
                img = generate_document(slug, name, category, variant, "back")
                path = out_dir / f"{slug}_back.png"
                img.save(path, "PNG")
                print(f"  Created: {path.relative_to(OUTPUT_DIR)}")
                total += 1

    print(f"\nDone! Generated {total} demo document images in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
