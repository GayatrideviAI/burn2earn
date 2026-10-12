from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import SimpleTestCase

from apps.core.geo import area_acres


class AreaAcresTests(SimpleTestCase):
    def test_one_square_kilometre_is_about_247_acres(self):
        # Near Ambala (lat 30.37): 1 km north-south is ~0.009009 deg of latitude,
        # 1 km east-west is ~0.010413 deg of longitude.
        lon, lat, dlon, dlat = 76.78, 30.37, 0.010413, 0.009009
        square = MultiPolygon(
            Polygon(
                (
                    (lon, lat),
                    (lon + dlon, lat),
                    (lon + dlon, lat + dlat),
                    (lon, lat + dlat),
                    (lon, lat),
                )
            ),
            srid=4326,
        )
        self.assertAlmostEqual(float(area_acres(square)), 247.1, delta=3)

    def test_geometry_without_srid_is_rejected(self):
        polygon = Polygon(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0)))
        with self.assertRaises(ValueError):
            area_acres(polygon)
