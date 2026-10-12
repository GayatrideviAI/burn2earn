from django.db import migrations

# Two active GeoCells may share an edge but never an area. A plain PostGIS
# exclusion constraint cannot express "touching is fine", so a trigger checks the
# interiors with ST_Relate. The pattern '2********' means "the interiors intersect
# in a 2-dimensional area", which is exactly an overlap.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION territory_geocell_reject_overlap() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'active' AND EXISTS (
        SELECT 1 FROM territory_geocell g
        WHERE g.id <> NEW.id
          AND g.status = 'active'
          AND g.boundary && NEW.boundary
          AND ST_Relate(g.boundary, NEW.boundary, '2********')
    ) THEN
        RAISE EXCEPTION 'GeoCell overlaps an existing active GeoCell'
            USING ERRCODE = 'exclusion_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CREATE_TRIGGER = """
CREATE TRIGGER territory_geocell_no_overlap
BEFORE INSERT OR UPDATE OF boundary, status ON territory_geocell
FOR EACH ROW EXECUTE FUNCTION territory_geocell_reject_overlap();
"""

DROP_TRIGGER = "DROP TRIGGER IF EXISTS territory_geocell_no_overlap ON territory_geocell;"
DROP_FUNCTION = "DROP FUNCTION IF EXISTS territory_geocell_reject_overlap();"


class Migration(migrations.Migration):
    dependencies = [
        ("territory", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[CREATE_FUNCTION, CREATE_TRIGGER],
            reverse_sql=[DROP_TRIGGER, DROP_FUNCTION],
        ),
    ]
