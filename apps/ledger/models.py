from django.conf import settings
from django.db import models


class LedgerEntry(models.Model):
    """One line in the append-only ledger.

    Each entry carries a hash of the entry before it, so changing or removing any past
    entry breaks every hash after it. The database also refuses UPDATE and DELETE on this
    table. This is a tamper-evident chain kept in our own database, not a public blockchain.
    """

    seq = models.PositiveBigIntegerField(unique=True)
    entry_type = models.CharField(max_length=64, db_index=True)
    subject_type = models.CharField(max_length=40, db_index=True)
    subject_id = models.CharField(max_length=64, db_index=True)
    # Canonical JSON text (sorted keys, no spaces), so the hash can always be recomputed.
    payload_text = models.TextField()
    created_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["seq"]
        verbose_name_plural = "ledger entries"

    def __str__(self):
        return f"#{self.seq} {self.entry_type} {self.subject_type} {self.subject_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Ledger entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Ledger entries cannot be deleted.")
