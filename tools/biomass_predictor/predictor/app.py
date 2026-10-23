import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from . import engine, vision
from .factors import FACTORS
from .limits import Limiter

STATIC = Path(__file__).parent / "static"
CAVEATS = [
    "This is a rough estimate from one photo, not a measurement. Weigh before you trade.",
    "The conversion numbers are published figures or placeholders and have not been confirmed by a technical team.",
    "Money figures are a guide. Real straw prices are set by Regenerix, and carbon credits depend on a registered, verified project.",
    "The photo reader has not yet been checked against weighed piles.",
]


CARBON_SHARE = min(1.0, max(0.0, float(os.environ.get("PREDICTOR_FARMER_CARBON_SHARE", 1.0))))


def client_ip(request):
    if os.environ.get("PREDICTOR_TRUST_PROXY") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def create_app(reader=None, limiter=None):
    reader = reader or vision.AnthropicVision()
    limiter = limiter or Limiter(
        per_ip=int(os.environ.get("PREDICTOR_PER_IP_HOURLY", 10)),
        daily_total=int(os.environ.get("PREDICTOR_DAILY_TOTAL", 500)),
    )

    async def index(request):
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def health(request):
        return JSONResponse({"ok": True})

    async def factors(request):
        return JSONResponse({"factors": [f.as_dict() for f in FACTORS.values()], "caveats": CAVEATS})

    async def estimate(request):
        def fail(message, status=400):
            return JSONResponse({"error": message}, status_code=status)

        try:
            form = await request.form(max_files=1, max_fields=12)
        except Exception:
            return fail("The form could not be read.")
        mode = form.get("mode")
        photo = form.get("photo")
        if mode not in ("bales", "field") or photo is None or not hasattr(photo, "read"):
            return fail("Choose bales or field and attach one photo.")
        try:
            ref_cm = float(form.get("ref_cm", ""))
        except ValueError:
            return fail("Enter how long the reference object is, in cm.")
        if not 5 <= ref_cm <= 1000:
            return fail("The reference length should be between 5 cm and 1000 cm.")
        ref_label = vision.clean_label(form.get("ref_label")) or "reference object"
        known = form.get("known_bale_kg") or None
        if known:
            try:
                float(known)
            except ValueError:
                return fail("Bale weight must be a number.")

        data = await photo.read(vision.MAX_UPLOAD_BYTES + 1)
        try:
            jpeg = vision.prepare_image(data)
        except vision.BadPhoto as error:
            return fail(str(error))

        limited = limiter.allow(client_ip(request))
        if limited:
            return fail(limited, 429)
        try:
            reading = await reader.analyse(jpeg, mode, ref_label, ref_cm)
        except vision.VisionUnavailable as error:
            return fail(str(error), 503)
        if not reading.get("usable", True):
            reason = str(reading.get("reason") or "The photo could not be used.")[:200]
            return fail(f"{reason} Try a clearer photo with the reference object in view.", 422)
        try:
            result = engine.estimate(mode, reading, known_bale_kg=known if mode == "bales" else None,
                                    carbon_share=CARBON_SHARE)
        except engine.BadReading as error:
            return fail(f"{error} Try another photo.", 422)
        result["caveats"] = CAVEATS
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    return Starlette(routes=[
        Route("/", index),
        Route("/healthz", health),
        Route("/api/factors", factors),
        Route("/api/estimate", estimate, methods=["POST"]),
    ])
