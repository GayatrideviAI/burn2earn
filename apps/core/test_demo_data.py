from django.core.management import call_command
from django.test import TestCase

from apps.farms.models import FarmPlot
from apps.farms.services import register_farmer
from apps.geography.models import Village
from apps.network.models import Mitra
from apps.territory.models import GeoCell


class DemoDataTests(TestCase):
    def test_loads_a_working_network_and_can_be_run_twice(self):
        call_command("load_demo_data", verbosity=0)
        call_command("load_demo_data", verbosity=0)
        self.assertEqual(GeoCell.objects.count(), 8)
        mitra = Mitra.objects.get()
        self.assertEqual(mitra.geocells.count(), 8)
        self.assertEqual(mitra.equipment.count(), 1)

    def test_the_mitra_can_log_in_and_register_a_farmer_with_a_plot(self):
        call_command("load_demo_data", verbosity=0)
        self.assertTrue(self.client.login(username="mitra1", password="mitra-demo-123"))
        self.assertEqual(self.client.get("/mitra/").status_code, 200)
        village = Village.objects.first()
        farmer = register_farmer(
            mitra=Mitra.objects.get(), name="Test", mobile="9811111111", village=village
        )
        from django.contrib.gis.geos import Point

        plot = FarmPlot.objects.create(
            farmer=farmer, location=Point(76.715, 30.315, srid=4326), area_acres=2
        )
        self.assertIsNotNone(plot.geocell)
