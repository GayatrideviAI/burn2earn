from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.accounts.models import User
from apps.field.tests import FieldTestCase
from apps.demand.tests import make_buyer, make_factory
from apps.operations.services import log_collection, submit_output
from apps.reference.models import BiomassType, ProcessingType, Product

from .models import Dispatch, EventType, FeeModel, FeeSchedule, Sale
from .services import create_dispatch, record_event, record_sale


class DispatchBase(FieldTestCase):
    def setUp(self):
        super().setUp()
        straw = BiomassType.objects.get(name="Paddy straw")
        self.product = Product.objects.create(
            name="Paddy pellets", form="processed", biomass_type=straw,
            processing_type=ProcessingType.objects.get(name="Pelletising"),
        )
        self.site = make_factory(make_buyer())
        submit_output(mitra=self.mitra, product=self.product, quantity_tonnes=Decimal("6"))


class MitraDispatchPageTests(DispatchBase):
    def test_mitra_creates_a_dispatch_and_sees_its_trail(self):
        response = self.client.post(
            reverse("field:dispatch_new"),
            {"product": self.product.pk, "factory": self.site.pk, "quantity_tonnes": "4"},
            follow=True,
        )
        self.assertContains(response, "DSP-000001")
        self.assertContains(response, "dispatch.created")
        self.assertEqual(Dispatch.objects.get().created_by_mitra, self.mitra)

    def test_cannot_send_more_than_available(self):
        response = self.client.post(
            reverse("field:dispatch_new"),
            {"product": self.product.pk, "factory": self.site.pk, "quantity_tonnes": "9"},
        )
        self.assertContains(response, "Only 6")
        self.assertEqual(Dispatch.objects.count(), 0)

    def test_list_shows_hub_steps_and_loss(self):
        d = create_dispatch(grid=self.grid, product=self.product, factory=self.site, quantity_tonnes=Decimal("4"), mitra=self.mitra)
        record_event(d, EventType.RECEIVED_AT_HUB, quantity_tonnes=Decimal("3.9"))
        page = self.client.get(reverse("field:dispatch_list"))
        self.assertContains(page, "At the Hub")
        self.assertContains(page, "lost 0.100 t")

    def test_other_grids_dispatches_are_not_shown(self):
        other_grid = self.make_grid("GRID-OTHER")
        Dispatch.objects.create(grid=other_grid, product=self.product, factory=self.site, quantity_tonnes=1)
        self.assertNotContains(self.client.get(reverse("field:dispatch_list")), "DSP-")


class TradeAdminTests(DispatchBase):
    def setUp(self):
        super().setUp()
        self.boss = User.objects.create_superuser(username="boss", password="pw-12345-x")
        self.client.force_login(self.boss)

    def test_admin_pages_open(self):
        for path in (
            "feeschedule", "dispatch", "sale", "leasecharge",
        ):
            self.assertEqual(self.client.get(f"/admin/trade/{path}/").status_code, 200, path)
            self.assertEqual(self.client.get(f"/admin/trade/{path}/add/").status_code, 200, path)
        self.assertEqual(self.client.get("/admin/ledger/ledgerentry/").status_code, 200)

    def test_admin_adds_a_step_and_the_sale_through_the_screens(self):
        FeeSchedule.objects.create(
            region=self.region, fee_model=FeeModel.PERCENTAGE, percentage=Decimal("10"), effective_from=date(2026, 1, 1)
        )
        log_collection(mitra=self.mitra, farmer=self.register(), biomass_type=BiomassType.objects.get(name="Paddy straw"), quantity_tonnes=2, price_paid=3000)
        d = create_dispatch(grid=self.grid, product=self.product, factory=self.site, quantity_tonnes=Decimal("4"), mitra=self.mitra)
        for event, weight in ((EventType.IN_TRANSIT, "4"), (EventType.DELIVERED, "3.9")):
            response = self.client.post(
                f"/admin/trade/dispatch/{d.pk}/change/",
                {
                    "vehicle_ref": "", "note": "",
                    "events-TOTAL_FORMS": "1", "events-INITIAL_FORMS": "0",
                    "events-MIN_NUM_FORMS": "0", "events-MAX_NUM_FORMS": "1000",
                    "events-0-event_type": event, "events-0-quantity_tonnes": weight,
                    "events-0-occurred_at_0": "2026-10-15", "events-0-occurred_at_1": "10:00:00",
                    "events-0-vehicle_ref": "", "events-0-note": "", "events-0-dispatch": str(d.pk),
                },
            )
            self.assertEqual(response.status_code, 302, getattr(response, "context_data", None) and response.context_data["errors"])
        d.refresh_from_db()
        self.assertEqual(d.stage, "delivered")
        response = self.client.post(
            "/admin/trade/sale/add/", {"dispatch": str(d.pk), "sale_value": "10000", "farmer_payment": "3000"}
        )
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get()
        self.assertEqual((sale.platform_fee, sale.mitra_margin), (Decimal("1000.00"), Decimal("6000.00")))
        self.client.post("/admin/trade/sale/", {"action": "buyer_paid", "_selected_action": [str(sale.pk)]})
        sale.refresh_from_db()
        self.assertEqual(sale.buyer_payment, "received")

    def test_admin_rejects_a_step_that_gains_weight(self):
        d = create_dispatch(grid=self.grid, product=self.product, factory=self.site, quantity_tonnes=Decimal("4"), mitra=self.mitra)
        response = self.client.post(
            f"/admin/trade/dispatch/{d.pk}/change/",
            {
                "vehicle_ref": "", "note": "",
                "events-TOTAL_FORMS": "1", "events-INITIAL_FORMS": "0",
                "events-MIN_NUM_FORMS": "0", "events-MAX_NUM_FORMS": "1000",
                "events-0-event_type": "in_transit", "events-0-quantity_tonnes": "5",
                "events-0-occurred_at_0": "2026-10-15", "events-0-occurred_at_1": "10:00:00",
                "events-0-vehicle_ref": "", "events-0-note": "", "events-0-dispatch": str(d.pk),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "gain weight")
        d.refresh_from_db()
        self.assertEqual(d.stage, "at_grid")
