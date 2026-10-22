from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.customers.models import Pile, Stockyard
from apps.yardops import services
from apps.yardops.models import YardOperator

PASSWORD = "yard-demo-123"

# pile label -> readings as (hours ago, °C)
READINGS = {
    "A-01": [(72, 41), (48, 46), (24, 53), (3, 59)],   # climbing fast: a "watch closely" alert
    "B-02": [(70, 38), (46, 39), (22, 39)],              # steady and cool
    "D-01": [(2, 72)],                                   # hot: "check twice a day"
    "D-02": [(5, 41)],                                   # cool, but the stack is too tall
}


class Command(BaseCommand):
    help = "Add a yard operator login (yard1) and sample temperatures, inspections and alerts to the demo customer's yards."

    @transaction.atomic
    def handle(self, *args, **options):
        call_command("load_demo_customer", verbosity=0)
        if User.objects.filter(username="yard1").exists():
            self.stdout.write("Yard demo already exists. Log in at /yard/ as yard1 / " + PASSWORD)
            return
        user = User.objects.create_user(username="yard1", password=PASSWORD, role=Role.YARD)
        operator = YardOperator.objects.create(user=user, name="Yard supervisor")
        operator.yards.set(Stockyard.objects.filter(name__in=["Yard A", "Yard B", "Yard C", "Yard D"]))
        now = timezone.now()
        piles = {p.label: p for p in Pile.objects.filter(yard__in=operator.yards.all())}
        services.update_pile_size(piles["D-02"], length_m=Decimal("20"), width_m=Decimal("8"), height_m=Decimal("5.5"))
        services.update_pile_size(piles["A-01"], length_m=Decimal("18"), width_m=Decimal("7"), height_m=Decimal("3.5"))
        for label, readings in READINGS.items():
            for hours, temp in readings:
                services.record_heat(piles[label], Decimal(temp), taken_at=now - timedelta(hours=hours), spot="north face, 1 m deep", taken_by="Yard supervisor")
        services.record_inspection(piles["A-03"], looks_wet=True, cover_in_place=False, notes="Rain came in under the roof", inspected_by="Yard supervisor")
        services.record_inspection(piles["B-02"], inspected_by="Yard supervisor", notes="All fine")
        self.stdout.write(self.style.SUCCESS(f"Yard demo ready. Log in at /yard/ as yard1 / {PASSWORD}"))
