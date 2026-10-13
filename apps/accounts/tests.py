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


class UserAdminPagesTests(TestCase):
    def test_add_user_page_opens_and_creates_a_mitra_login(self):
        admin_user = User.objects.create_superuser(username="boss", password="pw-12345-x")
        self.client.force_login(admin_user)
        self.assertEqual(self.client.get("/admin/accounts/user/add/").status_code, 200)
        response = self.client.post(
            "/admin/accounts/user/add/",
            {
                "username": "mitra9",
                "role": "mitra",
                "mobile": "",
                "usable_password": "true",
                "password1": "a-long-pass-123",
                "password2": "a-long-pass-123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.get(username="mitra9").role, "mitra")
