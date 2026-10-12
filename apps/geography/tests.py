import json
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from .models import Block, District, Panchayat, State, Village

CSV_HEADER = (
    "state_lgd,state_name,district_lgd,district_name,block_lgd,block_name,"
    "panchayat_lgd,panchayat_name,village_lgd,village_name\n"
)
CSV_ROWS = (
    "6,Haryana,43,Ambala,401,Ambala I,9001,Panchayat One,50001,Village A\n"
    "6,Haryana,43,Ambala,401,Ambala I,9002,Panchayat Two,50002,Village B\n"
)


def write_temp(directory, name, text):
    path = Path(directory) / name
    path.write_text(text, encoding="utf-8")
    return str(path)


class LoadGeographyTests(TestCase):
    def test_loads_the_whole_hierarchy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_temp(tmp, "geo.csv", CSV_HEADER + CSV_ROWS)
            call_command("load_geography", path)
        self.assertEqual(State.objects.count(), 1)
        self.assertEqual(District.objects.count(), 1)
        self.assertEqual(Block.objects.count(), 1)
        self.assertEqual(Panchayat.objects.count(), 2)
        self.assertEqual(Village.objects.count(), 2)
        self.assertEqual(Village.objects.get(lgd_code="50001").panchayat.name, "Panchayat One")

    def test_rerunning_does_not_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_temp(tmp, "geo.csv", CSV_HEADER + CSV_ROWS)
            call_command("load_geography", path)
            call_command("load_geography", path)
        self.assertEqual(Panchayat.objects.count(), 2)

    def test_missing_columns_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_temp(tmp, "bad.csv", "state_lgd,state_name\n6,Haryana\n")
            with self.assertRaises(CommandError):
                call_command("load_geography", path)


class LoadBoundariesTests(TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            call_command("load_geography", write_temp(tmp, "geo.csv", CSV_HEADER + CSV_ROWS))

    def feature(self, code):
        return {
            "type": "Feature",
            "properties": {"lgd_code": code},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[76.0, 30.0], [76.01, 30.0], [76.01, 30.01], [76.0, 30.01], [76.0, 30.0]]],
            },
        }

    def test_polygon_is_stored_as_multipolygon_on_the_matching_panchayat(self):
        collection = {
            "type": "FeatureCollection",
            "features": [self.feature("9001"), self.feature("0000")],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_temp(tmp, "b.geojson", json.dumps(collection))
            call_command("load_panchayat_boundaries", path)
        loaded = Panchayat.objects.get(lgd_code="9001")
        self.assertEqual(loaded.boundary.geom_type, "MultiPolygon")
        self.assertEqual(loaded.boundary.srid, 4326)
        self.assertIsNone(Panchayat.objects.get(lgd_code="9002").boundary)
