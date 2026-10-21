from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.demand.tests import make_buyer, make_factory
from apps.ledger.chain import entries_for, verify
from apps.operations.services import log_collection, submit_output
from apps.operations.tests import OperationsTestCase
from apps.trade.models import Dispatch, EventType
from apps.trade.services import create_dispatch, record_event

from . import contracts
from .models import Contract, ContractLine, CustomerMember, JobRole, MonthlyPlan, OrderState, PurchaseOrder

D = Decimal


def at(days_ago):
    return timezone.make_aware(datetime.combine(date.today() - timedelta(days=days_ago), time(12, 0)))


class SupplyCase(OperationsTestCase):
    def setUp(self):
        super().setUp()
        self.buyer = make_buyer()
        self.plant = make_factory(self.buyer)
        today = date.today()
        self.contract = Contract.objects.create(
            customer=self.buyer, start_date=today - timedelta(days=120), end_date=today + timedelta(days=240)
        )
        self.line = ContractLine.objects.create(contract=self.contract, product=self.pellets, contracted_tonnes=D("1000"))
        self.order = PurchaseOrder.objects.create(
            line=self.line, factory=self.plant, tonnes=D("100"), deliver_from=today - timedelta(days=20), deliver_by=today + timedelta(days=10)
        )
        earlier = today - timedelta(days=30)
        self.collect("10", "14000", collected_on=earlier)
        log_collection(mitra=self.mitra, farmer=self.second, biomass_type=self.straw, quantity_tonnes=D("30"), price_paid=D("42000"), collected_on=earlier)
        submit_output(mitra=self.mitra, product=self.pellets, quantity_tonnes=D("400"))

    @property
    def second(self):
        if not hasattr(self, "_second"):
            self._second = self.register("Second Farmer", mobile="9111111111")
        return self._second

    def send(self, tonnes, gate=None, order=None, days_ago=1, finish=True):
        d = create_dispatch(grid=self.grid, product=self.pellets, factory=self.plant, quantity_tonnes=D(tonnes),
                            mitra=self.mitra, purchase_order=order or self.order)
        if finish:
            record_event(d, EventType.IN_TRANSIT, quantity_tonnes=D(tonnes), occurred_at=at(days_ago + 1))
            record_event(d, EventType.DELIVERED, quantity_tonnes=D(gate or tonnes), occurred_at=at(days_ago))
        return d


class ProgressTests(SupplyCase):
    def test_delivered_means_the_weight_at_the_gate_and_in_transit_is_separate(self):
        self.send("40", gate="39")
        self.send("20", finish=False)
        p = contracts.order_progress(self.order)
        self.assertEqual((p.delivered, p.on_the_way, p.remaining, p.percent), (D("39"), D("20"), D("61"), 39))

    def test_a_cancelled_dispatch_counts_for_nothing(self):
        d = self.send("40", finish=False)
        record_event(d, EventType.CANCELLED)
        p = contracts.order_progress(self.order)
        self.assertEqual((p.delivered, p.on_the_way), (D("0"), D("0")))

    def test_over_delivery_is_shown_not_hidden(self):
        self.send("110")
        p = contracts.order_progress(self.order)
        self.assertEqual((p.remaining, p.over_delivered), (D("0"), D("10")))

    def test_an_order_is_late_only_when_open_unfinished_and_past_its_window(self):
        self.send("40")
        p = contracts.order_progress(self.order)
        self.assertFalse(p.overdue())
        self.assertTrue(p.overdue(date.today() + timedelta(days=11)))
        self.order.state = OrderState.CANCELLED
        self.assertFalse(contracts.order_progress(self.order).overdue(date.today() + timedelta(days=11)))

    def test_line_progress_groups_deliveries_by_the_month_they_arrived(self):
        MonthlyPlan.objects.create(line=self.line, month=date.today(), planned_tonnes=D("80"))
        self.send("30", days_ago=0)
        lp = contracts.line_progress(self.line)
        this_month = [m for m in lp.months if m[0] == date.today().replace(day=1)][0]
        self.assertEqual(this_month[1:], (D("80"), D("30"), D("-50")))
        self.assertEqual((lp.delivered, lp.ordered, lp.not_yet_ordered), (D("30"), D("100"), D("900")))

    def test_cancelled_orders_do_not_count_as_ordered(self):
        self.order.state = OrderState.CANCELLED
        self.order.save()
        self.assertEqual(contracts.line_progress(self.line).ordered, D("0"))

    def test_a_contract_that_is_far_behind_its_time_is_at_risk(self):
        self.send("50")  # 5% delivered with a fifth of the period gone
        cp = contracts.contract_progress(self.contract)
        self.assertTrue(cp.at_risk)
        titles = [a[1] for a in contracts.supply_actions(self.buyer)]
        self.assertIn("Contract behind", titles)

    def test_a_late_order_raises_an_action(self):
        self.order.deliver_by = date.today() - timedelta(days=1)
        self.order.save()
        titles = [a[1] for a in contracts.supply_actions(self.buyer)]
        self.assertIn("Delivery late", titles)


class DispatchAgainstOrderTests(SupplyCase):
    def test_the_dispatch_carries_the_order_and_the_ledger_records_it(self):
        d = self.send("40", finish=False)
        self.assertEqual(d.purchase_order, self.order)
        self.assertIn(self.order.code, entries_for(d).first().payload_text)
        self.assertTrue(verify().ok)

    def test_a_closed_order_takes_nothing_more(self):
        self.order.state = OrderState.FULFILLED
        self.order.save()
        with self.assertRaises(ValidationError):
            self.send("10", finish=False)

    def test_the_plant_and_product_must_match_the_order(self):
        other_plant = make_factory(self.buyer, name="Second plant")
        with self.assertRaises(ValidationError):
            create_dispatch(grid=self.grid, product=self.pellets, factory=other_plant, quantity_tonnes=D("5"), mitra=self.mitra, purchase_order=self.order)

    def test_an_order_for_another_companys_plant_is_refused(self):
        other = make_factory(make_buyer(company_name="Other Ltd"), name="Other plant")
        order = PurchaseOrder(line=self.line, factory=other, tonnes=D("5"), deliver_from=date.today(), deliver_by=date.today())
        with self.assertRaises(ValidationError) as caught:
            order.clean()
        self.assertIn("factory", caught.exception.message_dict)


class ProvenanceTests(SupplyCase):
    def test_delivered_tonnes_are_shared_among_farmers_by_what_each_handed_over(self):
        d = self.send("40")  # farmers handed over 10 t and 30 t, so 25% and 75%
        who = contracts.provenance([d])
        shares = {f.name: t for f, t in who.farmers.items()}
        self.assertEqual(shares["Ramesh Kumar"], D("10"))
        self.assertEqual(shares["Second Farmer"], D("30"))
        self.assertEqual(who.mitras, {self.mitra: D("40")})
        self.assertEqual(who.unattributed, D("0"))

    def test_pickups_after_the_delivery_do_not_count(self):
        d = self.send("40", days_ago=10)
        log_collection(mitra=self.mitra, farmer=self.second, biomass_type=self.straw, quantity_tonnes=D("500"), price_paid=D("1"))
        self.assertEqual(contracts.provenance([d]).farmers[self.second], D("30"))

    def test_nothing_is_attributed_when_there_are_no_pickups(self):
        from apps.operations.models import CollectionRecord

        d = self.send("40")
        CollectionRecord.objects.update(status="inactive")
        who = contracts.provenance([d])
        self.assertEqual((who.unattributed, who.farmers), (D("40"), {}))

    def test_undelivered_lots_are_left_out(self):
        d = self.send("40", finish=False)
        self.assertEqual(contracts.provenance([d]).delivered, D("0"))


class CustomerPageTests(SupplyCase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user(username="cust1", password="pw-12345-x", role=Role.BUYER)
        CustomerMember.objects.create(user=user, buyer=self.buyer, job_role=JobRole.PROCUREMENT)
        self.client.login(username="cust1", password="pw-12345-x")
        self.send("40", gate="39")

    def test_contract_pages_show_progress_and_the_supply_chain(self):
        self.assertContains(self.client.get(reverse("customers:contracts")), self.contract.code)
        page = self.client.get(reverse("customers:contract", args=[self.contract.pk]))
        self.assertContains(page, self.order.code)
        self.assertContains(page, "Where the delivered biomass came from")
        page = self.client.get(reverse("customers:order", args=[self.order.pk]))
        self.assertContains(page, "DSP-")
        self.assertContains(page, self.farmer.code)
        self.assertContains(page, self.mitra.name)

    def test_farmer_names_and_mobiles_are_never_shown_to_a_customer(self):
        page = self.client.get(reverse("customers:order", args=[self.order.pk]))
        self.assertNotContains(page, "Ramesh Kumar")
        self.assertNotContains(page, "9876543210")
        self.assertNotContains(page, "Second Farmer")

    def test_another_companys_contract_and_order_are_not_visible(self):
        other = make_buyer(company_name="Other Ltd")
        contract = Contract.objects.create(customer=other, start_date=date.today(), end_date=date.today() + timedelta(days=30))
        line = ContractLine.objects.create(contract=contract, product=self.pellets, contracted_tonnes=D("10"))
        order = PurchaseOrder.objects.create(line=line, factory=make_factory(other, name="Their plant"), tonnes=D("5"),
                                             deliver_from=date.today(), deliver_by=date.today())
        self.assertEqual(self.client.get(reverse("customers:contract", args=[contract.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("customers:order", args=[order.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("customers:contracts")), contract.code)

    def test_the_overview_lists_a_late_order(self):
        self.order.deliver_by = date.today() - timedelta(days=1)
        self.order.save()
        self.assertContains(self.client.get(reverse("customers:dashboard")), "Delivery late")


class MitraAndAdminTests(SupplyCase):
    def test_a_mitra_picks_the_order_when_creating_a_dispatch(self):
        from apps.field.forms import DispatchForm

        form = DispatchForm()
        label = form.fields["purchase_order"].label_from_instance(self.order)
        self.assertIn(self.order.code, label)
        self.assertIn("100.0 t still to send", label)
        self.assertEqual(list(form.fields["purchase_order"].queryset), [self.order])

    def test_admin_pages_open_and_spreading_a_plan_adds_up(self):
        boss = User.objects.create_superuser(username="boss", password="pw-12345-x")
        self.client.force_login(boss)
        for model in ("contract", "contractline", "purchaseorder"):
            self.assertEqual(self.client.get(f"/admin/customers/{model}/").status_code, 200, model)
            self.assertEqual(self.client.get(f"/admin/customers/{model}/add/").status_code, 200, model)
        self.client.post("/admin/customers/contractline/", {"action": "spread_evenly", "_selected_action": [str(self.line.pk)]})
        plan = self.line.plan.all()
        self.assertEqual(plan.count(), len(contracts.months_between(self.contract.start_date, self.contract.end_date)))
        self.assertEqual(sum(p.planned_tonnes for p in plan), D("1000"))
        self.assertEqual(self.client.get("/admin/trade/dispatch/add/").status_code, 200)


from django.test import TestCase


class DemoDeliveriesTests(TestCase):
    def test_the_demo_loads_twice_and_shows_progress_and_a_late_order(self):
        call_command("load_demo_deliveries", verbosity=0)
        call_command("load_demo_deliveries", verbosity=0)
        contract = Contract.objects.get()
        cp = contracts.contract_progress(contract)
        self.assertEqual(cp.delivered, D("445") + D("149"))  # 247 + 198 + 149 at the gate
        late = [a for a in contracts.supply_actions(contract.customer) if a[1] == "Delivery late"]
        self.assertEqual(len(late), 1)
        who = contracts.provenance(Dispatch.objects.filter(purchase_order__line__contract=contract))
        self.assertEqual(len(who.farmers), 3)
        self.assertTrue(verify().ok)
