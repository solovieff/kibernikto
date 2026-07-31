"""Image hosting helpers (legacy module).

Prefer :mod:`kibernikto.utils.image_hosting` — this module keeps the old
function signatures as a thin compatibility shim.
"""

from kibernikto.utils.image_hosting import image_hosting

URL = "https://api.imgbb.com/1/upload"


async def post(filename, name):
    """Post using a filename like 'image.jpg' (legacy, reads the file)."""
    with open(filename, "rb") as img:
        return await publish_image_file(img.read(), name)


async def publish_image_file(image_bytes, name, expiration: int | None = None):
    """Publish image bytes via the configured hosting provider."""
    return await image_hosting.publish(image_bytes, name)
