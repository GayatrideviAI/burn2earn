"""Adding to the ledger and checking that it has not been tampered with."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.core.current_user import get_current_user_id

from .models import LedgerEntry

GENESIS = "0" * 64


def _plain(value):
    """Turn a payload into JSON-safe plain values. Money and weights become strings."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Cannot put {type(value).__name__} in the ledger")


def canonical(payload):
    return json.dumps(_plain(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_hash(*, seq, prev_hash, entry_type, subject_type, subject_id, created_at, payload_text):
    material = "|".join([str(seq), prev_hash, entry_type, subject_type, str(subject_id), created_at.isoformat(), payload_text])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def append(entry_type, subject, payload):
    """Add one entry. `subject` is the record it is about (a model instance).

    Appending is serialised by locking a counter row, so two people acting at the same moment
    still get a single, gap-free chain.
    """
    from apps.core.models import Counter

    with transaction.atomic():
        Counter.objects.get_or_create(name="ledger")
        counter = Counter.objects.select_for_update().get(name="ledger")
        counter.value += 1
        counter.save(update_fields=["value"])
        previous = LedgerEntry.objects.order_by("-seq").first()
        prev_hash = previous.hash if previous else GENESIS
        created_at = timezone.now()
        payload_text = canonical(payload)
        subject_type = subject._meta.label_lower
        entry = LedgerEntry(
            seq=counter.value,
            entry_type=entry_type,
            subject_type=subject_type,
            subject_id=str(subject.pk),
            payload_text=payload_text,
            created_at=created_at,
            created_by_id=get_current_user_id(),
            prev_hash=prev_hash,
            hash=compute_hash(
                seq=counter.value,
                prev_hash=prev_hash,
                entry_type=entry_type,
                subject_type=subject_type,
                subject_id=subject.pk,
                created_at=created_at,
                payload_text=payload_text,
            ),
        )
        entry.save()
    return entry


@dataclass
class Verification:
    ok: bool
    checked: int
    problem: str = ""
    first_bad_seq: int = None


def verify():
    """Walk the whole chain and report the first thing that does not add up."""
    expected_prev, expected_seq, checked = GENESIS, 1, 0
    for entry in LedgerEntry.objects.order_by("seq").iterator():
        if entry.seq != expected_seq:
            return Verification(False, checked, f"Entry {expected_seq} is missing (found {entry.seq}).", expected_seq)
        if entry.prev_hash != expected_prev:
            return Verification(False, checked, f"Entry {entry.seq} does not follow the one before it.", entry.seq)
        recomputed = compute_hash(
            seq=entry.seq,
            prev_hash=entry.prev_hash,
            entry_type=entry.entry_type,
            subject_type=entry.subject_type,
            subject_id=entry.subject_id,
            created_at=entry.created_at,
            payload_text=entry.payload_text,
        )
        if recomputed != entry.hash:
            return Verification(False, checked, f"Entry {entry.seq} has been altered.", entry.seq)
        expected_prev, expected_seq, checked = entry.hash, expected_seq + 1, checked + 1
    return Verification(True, checked)


def entries_for(subject):
    return LedgerEntry.objects.filter(subject_type=subject._meta.label_lower, subject_id=str(subject.pk))
