"""Add a demo contract, purchase orders and deliveries for the demo customer, supplied by the demo Mitra.

Loads the Haryana demo network and the demo customer first if they are missing. The figures are invented.
Safe to re-run.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.customers import contracts
from apps.customers.models import Contract, ContractLine, MonthlyPlan, PurchaseOrder
from apps.demand.models import Buyer
from apps.farms.services import register_farmer
from apps.geography.models import Village
from apps.network.models import Mitra
from apps.operations.services import log_collection, submit_output
from apps.reference.models import BiomassType, ProcessingType, Product
from apps.trade.models import EventType
from apps.trade.services import create_dispatch, record_event

D = Decimal


def at(days_ago):
    return timezone.make_aware(datetime.combine(date.today() - timedelta(days=days_ago), time(14, 0)))


class Command(BaseCommand):
    help = "Add a demo contract with purchase orders and deliveries from the demo Mitra's farmers."

    @transaction.atomic
    def handle(self, *args, **options):
        call_command("load_demo_data", site="haryana", verbosity=0)
        call_command("load_demo_customer", verbosity=0)
        buyer = Buyer.objects.get(company_name="Sample Power Ltd")
        if Contract.objects.filter(customer=buyer).exists():
            self.stdout.write("Demo contract already exists. Log in at /customer/ and open Contracts.")
            return
        plant = buyer.factories.first()
        mitra = Mitra.objects.get(user__username="mitra1")
        straw = BiomassType.objects.get(name="Paddy straw")
        product, _ = Product.objects.get_or_create(
            name="Paddy straw pellets", grade="A",
            defaults={"form": "processed", "biomass_type": straw, "processing_type": ProcessingType.objects.get(name="Pelletising")},
        )
        village = Village.objects.order_by("name").first()
        farmers = [
            register_farmer(mitra=mitra, name=name, mobile=mobile, village=village)
            for name, mobile in (("Demo Farmer One", "9811100001"), ("Demo Farmer Two", "9811100002"), ("Demo Farmer Three", "9811100003"))
        ]
        for farmer, tonnes in zip(farmers, (600, 300, 100)):
            log_collection(mitra=mitra, farmer=farmer, biomass_type=straw, quantity_tonnes=D(tonnes), price_paid=D(tonnes) * 1400,
                           collected_on=date.today() - timedelta(days=60))
        submit_output(mitra=mitra, product=product, quantity_tonnes=D("900"))

        contract = Contract.objects.create(
            customer=buyer, reference="SPL/BIO/2026-27", start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
            penalties="1% of the load value per day late, after 3 days' grace.",
        )
        line = ContractLine.objects.create(contract=contract, product=product, contracted_tonnes=D("3000"),
                                           price_per_tonne=D("9200"), max_moisture_percent=D("12"))
        months = contracts.months_between(contract.start_date, contract.end_date)
        for month in months:
            MonthlyPlan.objects.create(line=line, month=month, planned_tonnes=D("250"))
        due_now = PurchaseOrder.objects.create(line=line, factory=plant, customer_po_number="4500012345", tonnes=D("600"),
                                               deliver_from=date.today() - timedelta(days=50), deliver_by=date.today() - timedelta(days=5))
        coming = PurchaseOrder.objects.create(line=line, factory=plant, customer_po_number="4500012399", tonnes=D("500"),
                                              deliver_from=date.today(), deliver_by=date.today() + timedelta(days=30))
        grid = mitra.current_grid
        for order, tonnes, gate, days_ago in ((due_now, "250", "247", 35), (due_now, "200", "198", 20), (coming, "150", "149", 3)):
            d = create_dispatch(grid=grid, product=product, factory=plant, quantity_tonnes=D(tonnes), mitra=mitra, purchase_order=order,
                                vehicle_ref="HR-61-1234")
            record_event(d, EventType.IN_TRANSIT, quantity_tonnes=D(tonnes), occurred_at=at(days_ago + 1))
            record_event(d, EventType.DELIVERED, quantity_tonnes=D(gate), occurred_at=at(days_ago))
        create_dispatch(grid=grid, product=product, factory=plant, quantity_tonnes=D("120"), mitra=mitra, purchase_order=coming)
        self.stdout.write(self.style.SUCCESS("Demo contract ready. Log in at /customer/ as customer1 and open Contracts."))
