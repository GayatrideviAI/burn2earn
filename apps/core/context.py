from django.conf import settings


def predictor(request):
    """Makes the address of the stand-alone biomass predictor available to templates ("" = not set up)."""
    return {"PREDICTOR_URL": settings.PREDICTOR_URL}
