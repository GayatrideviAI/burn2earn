import json
import re

from django.urls import reverse

from apps.customers import i18n_tools as tools

from . import jscatalog
from .tests import FieldTestCase


class MitraLanguageTests(FieldTestCase):
    def switch(self, code, to="field:farmer_list"):
        response = self.client.post(reverse("set_language"), {"language": code, "next": reverse(to)})
        self.assertEqual(response.status_code, 302)
        return self.client.get(reverse(to))

    def test_english_is_the_default(self):
        page = self.client.get(reverse("field:farmer_list"))
        self.assertContains(page, "Register a farmer")
        self.assertContains(page, '<html lang="en">')

    def test_pages_follow_the_chosen_language(self):
        self.assertContains(self.switch("hi"), "किसान दर्ज करें")
        self.assertContains(self.switch("pa"), "ਕਿਸਾਨ ਦਰਜ ਕਰੋ")
        # and the choice sticks on other pages
        self.assertContains(self.client.get(reverse("field:stock")), "ਤੁਹਾਡੀ ਥਾਂ ਉੱਤੇ ਸਟਾਕ")

    def test_form_labels_and_choice_labels_are_translated(self):
        page = self.switch("hi", "field:farmer_new")
        self.assertContains(page, "मोबाइल नंबर")
        self.assertContains(page, "पसंदीदा भाषा")
        self.assertContains(page, "पंजाबी")  # the Punjabi option of the farmer's language

    def test_messages_after_saving_are_translated(self):
        self.switch("hi")
        response = self.client.post(reverse("field:farmer_new"), self.farmer_data(), follow=True)
        self.assertContains(response, "दर्ज हो गए")

    def test_a_validation_error_is_translated(self):
        self.switch("hi")
        data = self.farmer_data()
        del data["consent"]
        self.assertContains(self.client.post(reverse("field:farmer_new"), data), "सहमति ज़रूरी है")

    def test_a_phrase_without_a_translation_shows_english(self):
        self.assertContains(self.switch("hi", "field:dispatch_new"), "रवानगी बनाएँ")
        self.assertContains(self.switch("hi", "field:dashboard"), "Grid")  # 'Grid' is left for the field team

    def test_the_language_switch_is_on_the_page(self):
        page = self.client.get(reverse("field:dashboard"))
        for name in ("English", "हिन्दी", "ਪੰਜਾਬੀ"):
            self.assertContains(page, name)


class OfflineAppLanguageTests(FieldTestCase):
    def catalog(self, page):
        match = re.search(r"catalog: (\{.*\})\n", page.content.decode())
        return json.loads(match.group(1))

    def test_the_offline_page_carries_the_translations(self):
        catalog = self.catalog(self.client.get(reverse("field:app")))
        self.assertEqual(set(catalog), {"hi", "pa"})
        self.assertEqual(catalog["hi"]["Farmers"], "किसान")
        self.assertEqual(catalog["pa"]["Hello, %(name)s"], "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, %(name)s")

    def test_phrases_without_a_translation_are_left_out_so_english_shows(self):
        catalog = self.catalog(self.client.get(reverse("field:app")))
        self.assertNotIn("Grid %(code)s", catalog["hi"])

    def test_every_phrase_in_the_phone_app_is_in_the_sheet(self):
        in_app = set(jscatalog.phrases_in(jscatalog.Path(jscatalog.__file__).parent / "static/field/app.js"))
        self.assertTrue(in_app)
        self.assertLessEqual(in_app, set(tools.collect()))

    def test_both_phrase_finders_agree(self):
        path = jscatalog.Path(jscatalog.__file__).parent / "static/field/app.js"
        self.assertEqual(sorted(jscatalog.phrases_in(path)), sorted(p for p, _line in tools.scan_js(path)))
