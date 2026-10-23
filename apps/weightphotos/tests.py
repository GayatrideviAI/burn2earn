import io
import shutil
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import Role, User
from apps.customers.tests import make_batch, make_pile, make_yard
from apps.field.tests import FieldTestCase
from apps.ledger.chain import entries_for, verify
from apps.yardops.models import YardOperator
from apps.yardops.tests import RiskCase

from . import services
from .models import Source, Subject, WeightPhoto

D = Decimal
MEDIA = tempfile.mkdtemp(prefix="weightphotos-test-")


def jpeg(size=(640, 480), colour=(120, 160, 90), fmt="JPEG"):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, fmt)
    return out.getvalue()


def upload_file(**kw):
    return SimpleUploadedFile("anything.jpg", jpeg(**kw), content_type="image/jpeg")


def tearDownModule():
    shutil.rmtree(MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=MEDIA)
class YardPhotoCase(RiskCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="yard1", password="pw-12345-x", role=Role.YARD)
        self.operator = YardOperator.objects.create(user=self.user, name="Gurdeep")
        self.operator.yards.add(self.pile.yard)
        self.client.login(username="yard1", password="pw-12345-x")
        self.url = reverse("yardops:api_photos")

    def send(self, **extra):
        data = {"id": str(uuid.uuid4()), "subject": "stack", "pile_id": str(self.pile.pk), "image": upload_file()}
        data.update(extra)
        data = {k: v for k, v in data.items() if v is not None}
        return self.client.post(self.url, data)


class UploadTests(YardPhotoCase):
    def test_a_stack_photo_is_saved_with_its_details(self):
        pk = str(uuid.uuid4())
        when = (timezone.now() - timedelta(hours=2)).isoformat()
        response = self.send(id=pk, taken_at=when, bale_count="120", reference_note="2 m pole on the left", notes="north face")
        self.assertEqual(response.json()["status"], "ok")
        photo = WeightPhoto.objects.get()
        self.assertEqual((str(photo.pk), photo.subject, photo.source, photo.pile), (pk, "stack", "yard", self.pile))
        self.assertEqual((photo.bale_count, photo.taken_by, photo.taken_by_user), (120, "Gurdeep", self.user))
        self.assertTrue(photo.code.startswith("WPH-"))
        self.assertAlmostEqual((timezone.now() - photo.taken_at).total_seconds(), 7200, delta=120)
        self.assertEqual((photo.width, photo.height), (640, 480))
        self.assertEqual(len(photo.sha256), 64)
        self.assertTrue(photo.image.name.endswith(f"{pk}.jpg"))
        self.assertEqual(entries_for(photo).get().entry_type, "weightphoto.captured")
        self.assertTrue(verify().ok)

    def test_a_load_photo_with_a_weighbridge_slip(self):
        response = self.send(
            subject="load", pile_id=None, vehicle_type="truck", vehicle_ref="HR 26 AB 1234",
            weighed_tonnes="11.250", slip_number="S-77", weighed_on=timezone.localdate().isoformat(),
        )
        self.assertEqual(response.json()["status"], "ok")
        photo = WeightPhoto.objects.get()
        self.assertEqual((photo.vehicle_type, photo.weighed_tonnes, photo.slip_number), ("truck", D("11.250"), "S-77"))
        self.assertTrue(photo.has_weight)

    def test_sending_the_same_photo_twice_saves_it_once(self):
        pk = str(uuid.uuid4())
        self.assertEqual(self.send(id=pk).json()["status"], "ok")
        self.assertEqual(self.send(id=pk).json()["status"], "exists")
        self.assertEqual(WeightPhoto.objects.count(), 1)

    def test_someone_elses_id_is_refused(self):
        mine = self.send().json()
        other = User.objects.create_user(username="yard2", password="pw-12345-x", role=Role.YARD)
        op2 = YardOperator.objects.create(user=other, name="Other")
        op2.yards.add(self.pile.yard)
        self.client.login(username="yard2", password="pw-12345-x")
        response = self.send(id=mine["id"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("someone else", response.json()["message"])

    def test_bad_uploads_are_refused_with_a_reason(self):
        for kwargs, text in (
            ({"id": "nope"}, "photo id"),
            ({"subject": "banana"}, "stack or a loaded"),
            ({"subject": "load", "pile_id": None, "vehicle_type": "rocket"}, "vehicle type"),
            ({"pile_id": str(uuid.uuid4())}, "not found in your yards"),
            ({"taken_at": "yesterday"}, "valid date and time"),
            ({"taken_at": (timezone.now() + timedelta(days=1)).isoformat()}, "future"),
            ({"bale_count": "many"}, "whole number"),
            ({"weighed_tonnes": "heavy"}, "must be a number"),
            ({"weighed_tonnes": "-3"}, "Ensure"),
            ({"image": SimpleUploadedFile("x.jpg", b"not a photo", content_type="image/jpeg")}, "not a photo"),
            ({"image": upload_file(size=(100, 100))}, "pixels"),
            ({"image": SimpleUploadedFile("x.gif", jpeg(fmt="GIF"), content_type="image/gif")}, "JPEG, PNG or WEBP"),
        ):
            with self.subTest(text=text):
                response = self.send(**kwargs)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(text, response.json()["message"])
        self.assertEqual(WeightPhoto.objects.count(), 0)

    def test_a_stack_cannot_have_a_vehicle_and_a_load_cannot_be_in_a_pile(self):
        self.assertEqual(self.send(vehicle_ref="HR 1").status_code, 400)
        self.assertEqual(self.send(subject="load").status_code, 400)

    def test_a_missing_photo_is_refused(self):
        self.assertEqual(self.send(image=None).status_code, 400)

    def test_a_pile_in_another_yard_is_refused(self):
        other = make_pile(make_yard("Yard Z"), "Z-01")
        make_batch(self.buyer, other, "10", "14")
        self.assertEqual(self.send(pile_id=str(other.pk)).status_code, 400)

    def test_location_and_camera_details_are_not_kept(self):
        image = Image.new("RGB", (640, 480), (10, 20, 30))
        exif = Image.Exif()
        exif[0x010F] = "SecretPhone"
        out = io.BytesIO()
        image.save(out, "JPEG", exif=exif)
        self.send(image=SimpleUploadedFile("x.jpg", out.getvalue(), content_type="image/jpeg"))
        saved = Image.open(WeightPhoto.objects.get().image.path)
        self.assertEqual(len(saved.getexif()), 0)

    def test_an_oversized_photo_is_refused(self):
        with override_settings(WEIGHT_PHOTO_MAX_BYTES=1000):
            self.assertEqual(self.send().status_code, 400)

    def test_login_is_required_and_only_yard_logins_may_upload(self):
        self.client.logout()
        self.assertEqual(self.send().status_code, 302)
        User.objects.create_user(username="adm", password="pw-12345-x", role=Role.ADMIN)
        self.client.login(username="adm", password="pw-12345-x")
        self.assertEqual(self.send().status_code, 403)


class WeightTests(YardPhotoCase):
    def photo(self):
        self.send()
        return WeightPhoto.objects.get()

    def sync(self, *ops):
        import json

        response = self.client.post(reverse("yardops:api_sync"), data=json.dumps({"operations": list(ops)}), content_type="application/json")
        return response.json()["results"]

    def weigh_op(self, photo, **extra):
        data = {"photo_id": str(photo.pk), "weighed_tonnes": "9.5", "slip_number": "S-1"}
        data.update(extra)
        return {"id": str(uuid.uuid4()), "type": "photo.weigh", "data": data}

    def test_the_weighbridge_weight_can_be_added_later(self):
        photo = self.photo()
        self.assertEqual(self.sync(self.weigh_op(photo))[0]["status"], "ok")
        photo.refresh_from_db()
        self.assertEqual((photo.weighed_tonnes, photo.slip_number, photo.weighed_on), (D("9.5"), "S-1", timezone.localdate()))
        self.assertEqual([e.entry_type for e in entries_for(photo)], ["weightphoto.captured", "weightphoto.weighed"])

    def test_sending_the_same_weight_again_is_recognised_and_a_different_one_refused(self):
        photo = self.photo()
        self.sync(self.weigh_op(photo))
        self.assertEqual(self.sync(self.weigh_op(photo))[0]["status"], "exists")
        result = self.sync(self.weigh_op(photo, weighed_tonnes="12"))[0]
        self.assertEqual(result["status"], "error")
        self.assertIn("already has a weighed figure", result["message"])
        photo.refresh_from_db()
        self.assertEqual(photo.weighed_tonnes, D("9.5"))

    def test_bad_weights_and_unknown_photos_are_refused(self):
        photo = self.photo()
        for op, text in (
            (self.weigh_op(photo, weighed_tonnes="0"), "above zero"),
            (self.weigh_op(photo, weighed_tonnes="heavy"), "must be a number"),
            (self.weigh_op(photo, weighed_on="2999-01-01"), "future"),
            (self.weigh_op(photo, photo_id=str(uuid.uuid4())), "not found"),
            (self.weigh_op(photo, weighed_on="nope"), "valid date"),
        ):
            with self.subTest(text=text):
                result = self.sync(op)[0]
                self.assertEqual(result["status"], "error")
                self.assertIn(text, result["message"])

    def test_a_photo_taken_by_someone_in_another_yard_cannot_be_weighed(self):
        other_pile = make_pile(make_yard("Yard Z"), "Z-01")
        stranger = User.objects.create_user(username="s", password="x", role=Role.YARD)
        other = services.store_photo(
            pk=uuid.uuid4(), source="yard", subject="stack", data=jpeg(), taken_by_user=stranger, pile=other_pile
        )
        self.assertEqual(self.sync(self.weigh_op(other))[0]["status"], "error")

    def test_the_phone_is_told_which_photos_still_need_a_weight(self):
        photo = self.photo()
        listed = self.client.get(reverse("yardops:api_bootstrap")).json()["photos_to_weigh"]
        self.assertEqual([p["id"] for p in listed], [str(photo.pk)])
        self.sync(self.weigh_op(photo))
        self.assertEqual(self.client.get(reverse("yardops:api_bootstrap")).json()["photos_to_weigh"], [])

    def test_staff_can_correct_a_weight_and_it_is_recorded(self):
        photo = self.photo()
        services.record_weight(photo, D("9.5"), slip_number="S-1")
        services.record_weight(photo, D("10"), slip_number="S-1", allow_change=True, by="staff")
        photo.refresh_from_db()
        self.assertEqual(photo.weighed_tonnes, D("10"))
        last = entries_for(photo).order_by("seq").last()
        self.assertEqual(last.entry_type, "weightphoto.weighed")
        self.assertTrue(verify().ok)

    def test_coverage_counts_photos_with_a_weight(self):
        photo = self.photo()
        self.send(id=str(uuid.uuid4()))
        services.record_weight(photo, D("9.5"))
        stack = next(r for r in services.coverage() if r["subject"] == "stack")
        self.assertEqual((stack["photos"], stack["weighed"], stack["enough"]), (2, 1, False))


@override_settings(MEDIA_ROOT=MEDIA)
class ImageViewTests(YardPhotoCase):
    def test_only_staff_and_the_photographer_can_see_a_photo(self):
        self.send()
        photo = WeightPhoto.objects.get()
        url = reverse("weightphotos:image", args=[photo.pk])
        response = self.client.get(url)
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "image/jpeg"))
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 404)
        User.objects.create_user(username="other", password="pw-12345-x", role=Role.YARD)
        self.client.login(username="other", password="pw-12345-x")
        self.assertEqual(self.client.get(url).status_code, 404)
        User.objects.create_user(username="boss", password="pw-12345-x", role=Role.ADMIN, is_staff=True)
        self.client.login(username="boss", password="pw-12345-x")
        self.assertEqual(self.client.get(url).status_code, 200)


@override_settings(MEDIA_ROOT=MEDIA)
class MitraPhotoTests(FieldTestCase):
    def send(self, **extra):
        data = {"id": str(uuid.uuid4()), "subject": "load", "vehicle_type": "tractor_trolley", "image": upload_file()}
        data.update(extra)
        return self.client.post(reverse("field:api_photos"), data)

    def test_a_mitra_can_photograph_a_load_and_a_stack_at_the_grid(self):
        self.assertEqual(self.send().json()["status"], "ok")
        self.assertEqual(self.send(subject="stack", vehicle_type="", place_note="Grid shed").json()["status"], "ok")
        photos = WeightPhoto.objects.order_by("created_at")
        self.assertEqual([p.source for p in photos], ["mitra", "mitra"])
        self.assertEqual(photos[0].taken_by, self.mitra.name)

    def test_a_mitra_cannot_attach_a_pile(self):
        from apps.customers.tests import make_pile

        self.assertEqual(self.send(subject="stack", vehicle_type="", pile_id=str(make_pile().pk)).status_code, 400)

    def test_the_weight_can_be_added_through_the_normal_sync(self):
        import json

        photo_id = self.send().json()["id"]
        op = {"id": str(uuid.uuid4()), "type": "photo.weigh", "data": {"photo_id": photo_id, "weighed_tonnes": "6.2", "slip_number": "W-9"}}
        response = self.client.post(reverse("field:api_sync"), data=json.dumps({"operations": [op]}), content_type="application/json")
        self.assertEqual(response.json()["results"][0]["status"], "ok")
        self.assertEqual(WeightPhoto.objects.get().weighed_tonnes, D("6.2"))
        boot = self.client.get(reverse("field:api_bootstrap")).json()
        self.assertEqual(boot["photos_to_weigh"], [])

    def test_a_yard_login_cannot_use_the_mitra_endpoint(self):
        self.client.logout()
        User.objects.create_user(username="y", password="pw-12345-x", role=Role.YARD)
        self.client.login(username="y", password="pw-12345-x")
        self.assertNotEqual(self.send().status_code, 200)


@override_settings(MEDIA_ROOT=MEDIA)
class AdminAndCommandTests(YardPhotoCase):
    def setUp(self):
        super().setUp()
        self.send()
        self.send(subject="load", pile_id=None, weighed_tonnes="5", slip_number="S-5")
        self.staff = User.objects.create_superuser(username="root", password="pw-12345-x")

    def test_staff_see_photos_and_can_add_a_weight(self):
        self.client.login(username="root", password="pw-12345-x")
        photo = WeightPhoto.objects.filter(weighed_tonnes__isnull=True).get()
        page = self.client.get(reverse("admin:weightphotos_weightphoto_change", args=[photo.pk]))
        self.assertContains(page, "weighed_tonnes")
        response = self.client.post(
            reverse("admin:weightphotos_weightphoto_change", args=[photo.pk]),
            {"weighed_tonnes": "8.4", "slip_number": "A-1", "weighed_on": timezone.localdate().isoformat()},
        )
        self.assertEqual(response.status_code, 302)
        photo.refresh_from_db()
        self.assertEqual(photo.weighed_tonnes, D("8.4"))

    def test_the_csv_action_lists_the_selected_photos(self):
        self.client.login(username="root", password="pw-12345-x")
        ids = [str(p.pk) for p in WeightPhoto.objects.all()]
        response = self.client.post(
            reverse("admin:weightphotos_weightphoto_changelist"), {"action": "download_csv", "_selected_action": ids}
        )
        text = response.content.decode()
        self.assertEqual(text.count("\n"), 3)
        self.assertIn("WPH-", text)
        self.assertIn("S-5", text)

    def test_nobody_can_add_or_delete_a_photo_in_admin(self):
        self.client.login(username="root", password="pw-12345-x")
        self.assertEqual(self.client.get(reverse("admin:weightphotos_weightphoto_add")).status_code, 403)

    def test_report_and_dataset_export(self):
        out = io.StringIO()
        call_command("weight_photo_report", stdout=out)
        self.assertIn("1 with a weighed figure", out.getvalue())
        folder = tempfile.mkdtemp(prefix="weightphotos-export-") + "/set"
        call_command("export_weight_dataset", folder, stdout=io.StringIO())
        import csv, os

        rows = list(csv.DictReader(open(os.path.join(folder, "labels.csv"))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["weighed_tonnes"], "5.000")
        self.assertTrue(os.path.exists(os.path.join(folder, "images", rows[0]["code"] + ".jpg")))
        shutil.rmtree(os.path.dirname(folder), ignore_errors=True)
