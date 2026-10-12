from django.db import transaction

from .models import ConsentRecord, Farmer

# Bump this whenever the wording of the farmer notice changes. "draft" means the
# wording has not yet been reviewed by counsel.
NOTICE_VERSION = "draft-1"


def register_farmer(*, mitra, name, mobile, village, preferred_language=""):
    """Register a farmer and record their consent in one step.

    A farmer is never saved without a consent record: both are created together
    or not at all.
    """
    with transaction.atomic():
        farmer = Farmer.objects.create(
            name=name,
            mobile=mobile,
            village=village,
            preferred_language=preferred_language,
            registered_by_mitra=mitra,
        )
        ConsentRecord.objects.create(
            farmer=farmer,
            notice_version=NOTICE_VERSION,
            language=preferred_language,
            captured_by_mitra=mitra,
        )
    return farmer
