from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from apps.accounts.models import User

from .chain import GENESIS, append, canonical, entries_for, verify
from .models import LedgerEntry


class LedgerTests(TestCase):
    def setUp(self):
        self.subject = User.objects.create_user(username="s", password="x")

    def add(self, kind="test.event", **payload):
        return append(kind, self.subject, payload or {"n": 1})

    def test_entries_are_numbered_and_linked(self):
        first, second = self.add(), self.add()
        self.assertEqual((first.seq, second.seq), (1, 2))
        self.assertEqual(first.prev_hash, GENESIS)
        self.assertEqual(second.prev_hash, first.hash)

    def test_a_clean_chain_verifies(self):
        for _ in range(3):
            self.add()
        result = verify()
        self.assertTrue(result.ok)
        self.assertEqual(result.checked, 3)

    def test_empty_ledger_is_intact(self):
        self.assertTrue(verify().ok)

    def test_money_and_weights_are_stored_as_exact_text(self):
        entry = self.add(amount=Decimal("1234.50"), tonnes=Decimal("2.500"))
        self.assertEqual(entry.payload_text, '{"amount":"1234.50","tonnes":"2.500"}')

    def test_payload_key_order_does_not_matter(self):
        self.assertEqual(canonical({"b": 1, "a": 2}), canonical({"a": 2, "b": 1}))

    def test_entries_can_be_found_by_subject(self):
        self.add()
        other = User.objects.create_user(username="o", password="x")
        append("test.event", other, {"n": 2})
        self.assertEqual(entries_for(self.subject).count(), 1)

    def test_python_refuses_to_change_or_delete(self):
        entry = self.add()
        entry.entry_type = "changed"
        with self.assertRaises(PermissionError):
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()

    def test_the_database_refuses_to_update_or_delete(self):
        entry = self.add()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerEntry.objects.filter(pk=entry.pk).update(payload_text="{}")
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerEntry.objects.filter(pk=entry.pk).delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM ledger_ledgerentry")

    def tamper(self, entry, **changes):
        """Rewrite a row the way someone who switched the trigger off would."""
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE ledger_ledgerentry DISABLE TRIGGER ledger_append_only")
            try:
                for column, value in changes.items():
                    cursor.execute(f"UPDATE ledger_ledgerentry SET {column} = %s WHERE id = %s", [value, entry.pk])
            finally:
                cursor.execute("ALTER TABLE ledger_ledgerentry ENABLE TRIGGER ledger_append_only")

    def test_an_edited_entry_is_detected(self):
        first = self.add(amount="100")
        self.add()
        self.tamper(first, payload_text='{"amount":"999"}')
        result = verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, first.seq)

    def test_a_removed_entry_is_detected(self):
        self.add()
        middle = self.add()
        self.add()
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE ledger_ledgerentry DISABLE TRIGGER ledger_append_only")
            cursor.execute("DELETE FROM ledger_ledgerentry WHERE id = %s", [middle.pk])
            cursor.execute("ALTER TABLE ledger_ledgerentry ENABLE TRIGGER ledger_append_only")
        result = verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, middle.seq)

    def test_a_rewritten_hash_alone_breaks_the_next_link(self):
        first = self.add()
        self.add()
        self.tamper(first, hash="f" * 64)
        self.assertFalse(verify().ok)

    def test_the_actor_is_recorded(self):
        from apps.core.current_user import reset_current_user, set_current_user

        token = set_current_user(self.subject)
        try:
            entry = self.add()
        finally:
            reset_current_user(token)
        self.assertEqual(entry.created_by, self.subject)
