"""Attach boundary polygons to panchayats from a GeoJSON file.

Each feature needs a property holding the panchayat's LGD code (default
``lgd_code``; change it with --code-property). Boundaries must be lon/lat
(EPSG:4326). Invalid polygons are repaired; features whose code matches no
panchayat are reported, not loaded.
"""

import json

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.geography.models import Panchayat


class Command(BaseCommand):
    help = "Load panchayat boundary polygons from a GeoJSON file."

    def add_arguments(self, parser):
        parser.add_argument("geojson_path", help="Path to the GeoJSON file")
        parser.add_argument(
            "--code-property",
            default="lgd_code",
            help="Feature property that holds the panchayat LGD code (default: lgd_code)",
        )

    @transaction.atomic
    def handle(self, geojson_path, code_property, **options):
        with open(geojson_path, encoding="utf-8") as handle:
            data = json.load(handle)
        features = data["features"] if data.get("type") == "FeatureCollection" else [data]

        updated, unmatched, skipped = 0, [], []
        for feature in features:
            code = str((feature.get("properties") or {}).get(code_property, "")).strip()
            if not code or not feature.get("geometry"):
                skipped.append(code or "<no code>")
                continue

            geometry = GEOSGeometry(json.dumps(feature["geometry"]), srid=4326)
            if not geometry.valid:
                geometry = geometry.buffer(0)
            if geometry.geom_type == "Polygon":
                geometry = MultiPolygon(geometry, srid=4326)
            if geometry.geom_type != "MultiPolygon":
                skipped.append(code)
                continue

            try:
                panchayat = Panchayat.objects.get(lgd_code=code)
            except Panchayat.DoesNotExist:
                unmatched.append(code)
                continue
            panchayat.boundary = geometry
            panchayat.save()
            updated += 1

        if not features:
            raise CommandError("No features found in the GeoJSON file.")
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} panchayat boundaries."))
        if unmatched:
            self.stdout.write(
                self.style.WARNING(f"No panchayat found for codes: {', '.join(unmatched)}")
            )
        if skipped:
            self.stdout.write(
                self.style.WARNING(f"Skipped features without a usable code or polygon: {len(skipped)}")
            )
