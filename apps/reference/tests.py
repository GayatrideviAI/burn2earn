from django.test import TestCase

from .models import Crop, Season


class StarterDataTests(TestCase):
    def test_starter_crops_are_available(self):
        names = set(Crop.objects.values_list("name", flat=True))
        self.assertEqual(names, {"Paddy", "Wheat", "Maize", "Cotton", "Mustard", "Sugarcane", "Soybean", "Millets"})

    def test_starter_seasons_are_available(self):
        self.assertEqual(
            list(Season.objects.order_by("start_month").values_list("name", flat=True)),
            ["Kharif", "Rabi"],
        )


class BiomassTypeTests(TestCase):
    def test_paddy_straw_starts_at_1_point_3_tonnes_per_acre(self):
        from .models import BiomassType

        self.assertEqual(str(BiomassType.objects.get(name="Paddy straw").estimated_tonnes_per_acre), "1.30")

    def test_mustard_stalk_starts_at_1_point_2_tonnes_per_acre(self):
        from .models import BiomassType

        self.assertEqual(str(BiomassType.objects.get(name="Mustard stalk").estimated_tonnes_per_acre), "1.20")

    def test_other_crops_have_no_figure_yet(self):
        from .models import BiomassType

        known = {"Paddy straw", "Mustard stalk"}
        self.assertEqual(
            BiomassType.objects.exclude(name__in=known).filter(estimated_tonnes_per_acre__isnull=False).count(),
            0,
        )
