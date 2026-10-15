from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import TestCase

from apps.farms.models import FarmPlot
from apps.farms.services import register_farmer
from apps.geography.models import Village
from apps.network.models import Mitra
from apps.territory.models import GeoCell, Region


class DemoDataTests(TestCase):
    def test_haryana_site_loads_a_working_network_and_can_be_run_twice(self):
        call_command("load_demo_data", site="haryana", verbosity=0)
        call_command("load_demo_data", site="haryana", verbosity=0)
        self.assertEqual(GeoCell.objects.count(), 8)
        mitra = Mitra.objects.get()
        self.assertEqual(mitra.geocells.count(), 8)
        self.assertEqual(mitra.equipment.count(), 1)

    def test_tamil_nadu_site_loads_kanchipuram(self):
        call_command("load_demo_data", site="tamilnadu", verbosity=0)
        region = Region.objects.get()
        self.assertEqual(region.state.name, "Tamil Nadu")
        self.assertEqual(region.district.name, "Kanchipuram")
        self.assertEqual(GeoCell.objects.count(), 6)
        self.assertEqual(Mitra.objects.get().geocells.count(), 6)

    def test_punjab_site_loads_talwandi_sabo(self):
        call_command("load_demo_data", site="punjab", verbosity=0)
        region = Region.objects.get()
        self.assertEqual(region.state.name, "Punjab")
        self.assertEqual(region.code, "REG-PB-TAL-001")
        self.assertEqual(GeoCell.objects.count(), 6)

    def test_loading_all_sites_keeps_them_apart(self):
        call_command("load_demo_data", verbosity=0)
        call_command("load_demo_data", verbosity=0)
        self.assertEqual(Region.objects.count(), 3)
        self.assertEqual(Mitra.objects.count(), 3)
        self.assertEqual(GeoCell.objects.count(), 20)

    def test_a_demo_mitra_can_log_in_and_a_plot_lands_in_a_cell(self):
        call_command("load_demo_data", site="tamilnadu", verbosity=0)
        self.assertTrue(self.client.login(username="mitra2", password="mitra-demo-123"))
        self.assertEqual(self.client.get("/mitra/").status_code, 200)
        farmer = register_farmer(
            mitra=Mitra.objects.get(), name="Test", mobile="9811111111", village=Village.objects.first()
        )
        plot = FarmPlot.objects.create(
            farmer=farmer, location=Point(79.635, 12.795, srid=4326), area_acres=2
        )
        self.assertIsNotNone(plot.geocell)
