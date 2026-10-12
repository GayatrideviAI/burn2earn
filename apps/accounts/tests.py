from django.test import TestCase

from .models import Role, User


class UserTests(TestCase):
    def test_superuser_gets_the_admin_role(self):
        user = User.objects.create_superuser("root", password="pw-12345")
        self.assertEqual(user.role, Role.ADMIN)
        self.assertTrue(user.is_admin_role)

    def test_user_id_is_a_uuid(self):
        user = User.objects.create_user("mitra1", password="pw-12345", role=Role.MITRA)
        self.assertEqual(len(str(user.pk)), 36)
        self.assertFalse(user.is_admin_role)
