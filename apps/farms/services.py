from django.db import transaction

from .models import ConsentRecord, Farmer

# Bump this whenever the wording of the farmer notice changes. "draft" means the
# wording has not yet been reviewed by counsel.
NOTICE_VERSION = "draft-1"


def register_farmer(
    *, mitra, name, mobile, village, preferred_language="", pk=None, needs_review=False, consented_at=None
):
    """Register a farmer and record their consent in one step.

    A farmer is never saved without a consent record: both are created together
    or not at all. `pk` lets the offline app choose the id on the phone, so sending the
    same farmer twice cannot create two records. `consented_at` is when the Mitra actually
    explained the notice, which may be earlier than when the phone got a signal.
    """
    extra = {"id": pk} if pk else {}
    with transaction.atomic():
        farmer = Farmer.objects.create(
            name=name,
            mobile=mobile,
            village=village,
            preferred_language=preferred_language,
            registered_by_mitra=mitra,
            needs_review=needs_review,
            **extra,
        )
        consent = {"given_at": consented_at} if consented_at else {}
        ConsentRecord.objects.create(
            farmer=farmer,
            notice_version=NOTICE_VERSION,
            language=preferred_language,
            captured_by_mitra=mitra,
            **consent,
        )
    return farmer


def possible_duplicates(mobile, exclude=None):
    """Other active farmers with the same mobile number."""
    found = Farmer.objects.filter(mobile=mobile, status="active")
    if exclude is not None:
        found = found.exclude(pk=exclude)
    return found
