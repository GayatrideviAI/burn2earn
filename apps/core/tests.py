from django.test import TestCase

from apps.accounts.models import Role, User
from apps.core.current_user import reset_current_user, set_current_user
from apps.core.models import AuditLog, DeletionNotAllowed, Status
from apps.geography.models import State


class BaseModelTests(TestCase):
    def test_created_and_updated_by_follow_the_current_user(self):
        user = User.objects.create_user("admin1", password="pw-12345", role=Role.ADMIN)
        token = set_current_user(user)
        try:
            state = State.objects.create(lgd_code="6", name="Haryana")
        finally:
            reset_current_user(token)
        self.assertEqual(state.created_by_id, user.pk)
        self.assertEqual(state.updated_by_id, user.pk)

    def test_no_user_leaves_audit_fields_empty(self):
        state = State.objects.create(lgd_code="6", name="Haryana")
        self.assertIsNone(state.created_by_id)

    def test_records_cannot_be_deleted(self):
        state = State.objects.create(lgd_code="6", name="Haryana")
        with self.assertRaises(DeletionNotAllowed):
            state.delete()
        self.assertTrue(State.objects.filter(pk=state.pk).exists())

    def test_deactivate_sets_status(self):
        state = State.objects.create(lgd_code="6", name="Haryana")
        state.deactivate()
        state.refresh_from_db()
        self.assertEqual(state.status, Status.INACTIVE)


class AuditLogTests(TestCase):
    def test_create_is_logged_with_actor(self):
        user = User.objects.create_user("admin1", password="pw-12345", role=Role.ADMIN)
        token = set_current_user(user)
        try:
            state = State.objects.create(lgd_code="6", name="Haryana")
        finally:
            reset_current_user(token)
        log = AuditLog.objects.get(object_id=str(state.pk))
        self.assertEqual(log.action, AuditLog.Action.CREATE)
        self.assertEqual(log.actor_id, user.pk)
        self.assertEqual(log.model_label, "geography.State")
        self.assertEqual(log.changes["name"], [None, "Haryana"])

    def test_update_logs_only_changed_fields(self):
        state = State.objects.create(lgd_code="6", name="Haryana")
        state.name = "Haryana State"
        state.save()
        log = AuditLog.objects.filter(object_id=str(state.pk)).first()
        self.assertEqual(log.action, AuditLog.Action.UPDATE)
        self.assertEqual(log.changes, {"name": ["Haryana", "Haryana State"]})

    def test_save_without_changes_writes_nothing(self):
        state = State.objects.create(lgd_code="6", name="Haryana")
        before = AuditLog.objects.count()
        state.save()
        self.assertEqual(AuditLog.objects.count(), before)
