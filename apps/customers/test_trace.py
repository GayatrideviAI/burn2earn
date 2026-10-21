from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.demand.tests import make_buyer, make_factory
from apps.ledger.chain import entries_for, verify
from apps.reference.models import BiomassType

from . import contracts, services
from .models import Batch, CustomerMember, JobRole, TransactionKind
from .test_contracts import SupplyCase
from .tests import make_pile, make_yard

D = Decimal


class ReceiveDeliveryTests(SupplyCase):
    def setUp(self):
        super().setUp()
        self.load = self.send("40", gate="39")
        self.pile = make_pile(make_yard("Yard A"), "A-09", "protected")

    def test_a_delivered_load_becomes_a_linked_batch(self):
        b = services.receive_delivery(self.load, self.pile, "pellets", moisture=D("9"))
        self.assertEqual(b.source_dispatch, self.load)
        self.assertEqual(b.customer, self.buyer)
        self.assertEqual(b.intake_tonnes, D("39"))  # the weight at the gate, not the weight loaded
        self.assertEqual(b.source_grid, self.grid)
        self.assertIn(self.load.code, b.source_note)
        self.assertIn(self.mitra.name, b.source_note)
        self.assertEqual(services.book_tonnes(b), D("39"))
        self.assertIn(self.load.code, entries_for(b).first().payload_text)
        self.assertTrue(verify().ok)

    def test_a_load_can_be_split_across_piles_but_not_over_received(self):
        services.receive_delivery(self.load, self.pile, "pellets", tonnes=D("25"))
        self.assertEqual(contracts.dispatch_receipts(self.load)[2], D("14"))
        other = make_pile(self.pile.yard, "A-10")
        with self.assertRaises(ValidationError) as caught:
            services.receive_delivery(self.load, other, "pellets", tonnes=D("15"))
        self.assertIn("Only 14", str(caught.exception))
        services.receive_delivery(self.load, other, "pellets")
        self.assertEqual(contracts.dispatch_receipts(self.load)[2], D("0"))

    def test_only_delivered_loads_for_that_company_can_be_received(self):
        moving = self.send("5", finish=False)
        with self.assertRaises(ValidationError):
            services.receive_delivery(moving, self.pile, "pellets")
        other_buyer = make_buyer(company_name="Other Ltd")
        batch = Batch(customer=other_buyer, pile=self.pile, biomass_type=self.straw, form="pellets", source_dispatch=self.load, intake_tonnes=D("1"))
        with self.assertRaises(ValidationError):
            batch.check_source()

    def test_the_biomass_type_must_match(self):
        other_type = BiomassType.objects.exclude(pk=self.straw.pk).first()
        batch = Batch(customer=self.buyer, pile=self.pile, biomass_type=other_type, form="pellets", source_dispatch=self.load, intake_tonnes=D("1"))
        with self.assertRaises(ValidationError):
            batch.check_source()


class ChainOfCustodyTests(SupplyCase):
    def setUp(self):
        super().setUp()
        self.load = self.send("40", gate="40")
        self.pile = make_pile(make_yard("Yard A"), "A-09", "protected")
        self.batch = services.receive_delivery(self.load, self.pile, "pellets", tonnes=D("20"), moisture=D("9"))
        services.record_transaction(self.batch, TransactionKind.CONSUMPTION, D("8"))
        services.record_transaction(self.batch, TransactionKind.LOSS, D("1"), loss_cause="rain")

    def test_origin_scales_the_farmers_to_this_batch_and_summarises_what_happened_after(self):
        o = contracts.batch_origin(self.batch)
        self.assertEqual(o.share, D("0.5"))
        shares = {f.name: t for f, t in o.farmers}
        self.assertEqual(shares, {"Ramesh Kumar": D("5"), "Second Farmer": D("15")})  # 10 t and 30 t of 40 t, half of the load
        self.assertEqual((o.consumed, o.lost, o.lost_by_cause), (D("8"), D("1"), {"Rain": D("1")}))
        self.assertEqual((o.order, o.contract, o.mitra), (self.order, self.contract, self.mitra))

    def test_a_batch_with_no_delivery_has_no_origin(self):
        loose = Batch.objects.create(customer=self.buyer, pile=self.pile, biomass_type=self.straw, form="bales", intake_tonnes=D("5"))
        self.assertIsNone(contracts.batch_origin(loose).dispatch)

    def test_half_received_loads_raise_an_action_until_the_rest_is_in(self):
        titles = lambda: [a[1] for a in contracts.supply_actions(self.buyer)]
        self.assertIn("Not in a yard yet", titles())
        services.receive_delivery(self.load, make_pile(self.pile.yard, "A-10"), "pellets")
        self.assertNotIn("Not in a yard yet", titles())

    def test_the_farmer_trace_follows_one_farmer_to_the_batch_and_the_boiler(self):
        rows = contracts.farmer_trace(self.second)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tonnes"], D("30"))
        batch, share, origin = rows[0]["batches"][0]
        self.assertEqual((batch, share, origin.consumed), (self.batch, D("15"), D("8")))
        self.assertEqual(contracts.farmer_trace(self.register("Nobody Yet", mobile="9222222222")), [])


class TracePagesTests(SupplyCase):
    def setUp(self):
        super().setUp()
        self.load = self.send("40")
        self.pile = make_pile(make_yard("Yard A"), "A-09", "protected")
        self.batch = services.receive_delivery(self.load, self.pile, "pellets", tonnes=D("30"))
        user = User.objects.create_user(username="cust1", password="pw-12345-x", role=Role.BUYER)
        CustomerMember.objects.create(user=user, buyer=self.buyer, job_role=JobRole.ESG)

    def test_the_batch_page_shows_the_whole_chain_without_farmer_names(self):
        self.client.login(username="cust1", password="pw-12345-x")
        page = self.client.get(reverse("customers:batch", args=[self.batch.pk]))
        for expected in ("Chain of custody", self.farmer.code, self.mitra.name, self.load.code, self.order.code, self.contract.code, "75% of that load"):
            self.assertContains(page, expected)
        self.assertNotContains(page, "Ramesh Kumar")
        self.assertNotContains(page, "Second Farmer")

    def test_an_unlinked_batch_says_it_cannot_be_traced(self):
        loose = Batch.objects.create(customer=self.buyer, pile=self.pile, biomass_type=self.straw, form="bales", intake_tonnes=D("5"))
        self.client.login(username="cust1", password="pw-12345-x")
        self.assertContains(self.client.get(reverse("customers:batch", args=[loose.pk])), "cannot be traced back to farmers")

    def test_the_order_page_shows_where_each_load_went_and_what_is_missing(self):
        self.client.login(username="cust1", password="pw-12345-x")
        page = self.client.get(reverse("customers:order", args=[self.order.pk]))
        self.assertContains(page, self.batch.code)
        self.assertContains(page, "10.0 t not in a yard")


class AdminTraceTests(SupplyCase):
    def setUp(self):
        super().setUp()
        self.load = self.send("40")
        self.pile = make_pile(make_yard("Yard A"), "A-09", "protected")
        self.boss = User.objects.create_superuser(username="boss", password="pw-12345-x")

    def batch_form(self, tonnes):
        return {
            "status": "active", "customer": self.buyer.pk, "pile": self.pile.pk, "biomass_type": self.straw.pk, "form": "pellets",
            "source_dispatch": self.load.pk, "source_note": "", "received_on": date.today().isoformat(),
            "intake_tonnes": tonnes, "intake_moisture_percent": "9",
        }

    def test_admin_receives_a_load_into_a_batch_and_it_cannot_be_over_received(self):
        self.client.force_login(self.boss)
        response = self.client.post("/admin/customers/batch/add/", self.batch_form("25"))
        self.assertEqual(response.status_code, 302)
        batch = Batch.objects.get(source_dispatch=self.load)
        self.assertEqual((batch.source_grid, services.book_tonnes(batch)), (self.grid, D("25")))
        response = self.client.post("/admin/customers/batch/add/", self.batch_form("20"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "still to be put into the yard")

    def test_the_load_choices_are_only_delivered_loads(self):
        moving = self.send("5", finish=False)
        self.client.force_login(self.boss)
        page = self.client.get("/admin/customers/batch/add/")
        self.assertContains(page, self.load.code)
        self.assertNotContains(page, f">{moving.code} ")

    def test_the_trace_report_is_for_staff_and_finds_a_farmer_by_code(self):
        self.assertEqual(self.client.get("/admin/reports/trace/").status_code, 302)
        self.client.force_login(self.boss)
        services.receive_delivery(self.load, self.pile, "pellets")
        page = self.client.get("/admin/reports/trace/", {"farmer": self.second.code.lower()})
        self.assertContains(page, self.second.code)
        self.assertContains(page, self.load.code)
        self.assertContains(page, "Yard A/A-09")
        self.assertContains(self.client.get("/admin/reports/trace/", {"farmer": "FRM-999999"}), "No farmer has the code")


class DemoTraceTests(TestCase):
    def test_demo_has_linked_batches_and_one_unreceived_load(self):
        call_command("load_demo_deliveries", verbosity=0)
        self.assertEqual(Batch.objects.exclude(source_dispatch=None).count(), 2)
        buyer = Batch.objects.exclude(source_dispatch=None).first().customer
        actions = [a for a in contracts.supply_actions(buyer) if a[1] == "Not in a yard yet"]
        self.assertEqual(len(actions), 1)
        self.assertTrue(verify().ok)
