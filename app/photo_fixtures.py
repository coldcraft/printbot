"""
Procedural test images for the photo-printing path.
Lives as code (not as committed PNGs) so we don't ship binary fixtures.
"""

from io import BytesIO


def make_skimask(width: int = 600, height: int = 720) -> bytes:
    """
    Stylized balaclava silhouette with a soft top-to-bottom gradient,
    two oval eye holes, and a horizontal mouth slit. Multiple gray tones
    inside the head shape exercise the dithering path; the holes and
    background are pure white/black so edges stay crisp.
    """
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("L", (width, height), 255)

    head_box = (
        int(width * 0.13),
        int(height * 0.06),
        int(width * 0.87),
        int(height * 0.94),
    )

    grad = Image.new("L", (width, height), 255)
    gd = ImageDraw.Draw(grad)
    for y in range(height):
        v = int(45 + (y / height) * 95)
        gd.line((0, y, width, y), fill=v)

    mask = Image.new("L", (width, height), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse(head_box, fill=255)

    img = Image.composite(grad, img, mask)

    draw = ImageDraw.Draw(img)
    eye_top = int(height * 0.40)
    eye_bot = int(height * 0.50)
    draw.ellipse((int(width * 0.27), eye_top, int(width * 0.45), eye_bot), fill=255)
    draw.ellipse((int(width * 0.55), eye_top, int(width * 0.73), eye_bot), fill=255)

    draw.rectangle(
        (int(width * 0.34), int(height * 0.71), int(width * 0.66), int(height * 0.77)),
        fill=255,
    )

    img = img.filter(ImageFilter.GaussianBlur(radius=1.2))

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
