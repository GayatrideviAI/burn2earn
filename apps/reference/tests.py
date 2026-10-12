from django.test import TestCase

from .models import Crop, Season


class StarterDataTests(TestCase):
    def test_starter_crops_are_available(self):
        names = set(Crop.objects.values_list("name", flat=True))
        self.assertEqual(names, {"Paddy", "Wheat", "Maize", "Cotton", "Mustard", "Sugarcane"})

    def test_starter_seasons_are_available(self):
        self.assertEqual(
            list(Season.objects.order_by("start_month").values_list("name", flat=True)),
            ["Kharif", "Rabi"],
        )
