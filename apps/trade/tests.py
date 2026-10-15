from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.demand.tests import make_buyer, make_factory
from apps.ledger.chain import entries_for, verify
from apps.ledger.models import LedgerEntry
from apps.operations.services import submit_output
from apps.operations.tests import OperationsTestCase

from .models import BuyerPayment, DispatchStage, EventType, FeeModel, FeeSchedule, LeaseCharge
from .services import (
    available_to_dispatch,
    charge_lease,
    create_dispatch,
    mark_buyer_paid,
    mark_mitra_settled,
    record_event,
    record_sale,
)


class TradeTestCase(OperationsTestCase):
    def setUp(self):
        super().setUp()
        self.factory_site = make_factory(make_buyer())
        self.collect("10", "15000")  # Rs 1,500 per tonne paid to farmers
        submit_output(mitra=self.mitra, product=self.pellets, quantity_tonnes=Decimal("8"))

    def schedule(self, fee_model=FeeModel.FLAT, **params):
        defaults = {"flat_rupees_per_tonne": Decimal("200")} if fee_model == FeeModel.FLAT else {}
        defaults.update(params)
        return FeeSchedule.objects.create(
            region=self.region, fee_model=fee_model, effective_from=date(2026, 1, 1), **defaults
        )

    def dispatch(self, tonnes="5"):
        return create_dispatch(
            grid=self.grid, product=self.pellets, factory=self.factory_site, quantity_tonnes=Decimal(tonnes), mitra=self.mitra
        )

    def deliver(self, dispatch, hub_weight="4.9", final_weight="4.8"):
        record_event(dispatch, EventType.RECEIVED_AT_HUB, quantity_tonnes=Decimal(hub_weight))
        record_event(dispatch, EventType.IN_TRANSIT, quantity_tonnes=Decimal(hub_weight))
        record_event(dispatch, EventType.DELIVERED, quantity_tonnes=Decimal(final_weight))
        dispatch.refresh_from_db()
        return dispatch


class FeeScheduleTests(TradeTestCase):
    def test_flat_fee_is_rupees_per_tonne(self):
        self.assertEqual(self.schedule().fee_for_sale(Decimal("4.8"), Decimal("20000")), Decimal("960.00"))

    def test_percentage_fee_is_a_share_of_the_sale_value(self):
        schedule = self.schedule(FeeModel.PERCENTAGE, percentage=Decimal("7.5"))
        self.assertEqual(schedule.fee_for_sale(Decimal("4.8"), Decimal("20000")), Decimal("1500.00"))

    def test_lease_has_no_fee_on_each_sale(self):
        schedule = self.schedule(FeeModel.LEASE, lease_rupees_per_month=Decimal("25000"))
        self.assertEqual(schedule.fee_for_sale(Decimal("4.8"), Decimal("20000")), Decimal("0.00"))

    def test_the_figure_for_the_chosen_model_is_required(self):
        schedule = FeeSchedule(region=self.region, fee_model=FeeModel.PERCENTAGE, effective_from=date(2026, 1, 1))
        with self.assertRaises(ValidationError) as caught:
            schedule.clean()
        self.assertIn("percentage", caught.exception.message_dict)

    def test_a_region_has_only_one_open_schedule(self):
        self.schedule()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.schedule(FeeModel.PERCENTAGE, percentage=Decimal("5"))

    def test_the_schedule_in_force_on_a_date_is_found(self):
        old = self.schedule()
        old.effective_to = date(2026, 5, 31)
        old.save()
        new = FeeSchedule.objects.create(
            region=self.region, fee_model=FeeModel.PERCENTAGE, percentage=Decimal("6"), effective_from=date(2026, 6, 1)
        )
        self.assertEqual(FeeSchedule.current_for(self.region, date(2026, 3, 1)), old)
        self.assertEqual(FeeSchedule.current_for(self.region, date(2026, 7, 1)), new)
        self.assertIsNone(FeeSchedule.current_for(self.region, date(2025, 1, 1)))


class DispatchTests(TradeTestCase):
    def test_only_made_product_not_already_sent_is_available(self):
        self.assertEqual(available_to_dispatch(self.grid, self.pellets), Decimal("8"))
        self.dispatch("5")
        self.assertEqual(available_to_dispatch(self.grid, self.pellets), Decimal("3"))

    def test_cannot_send_more_than_was_made(self):
        with self.assertRaises(ValidationError):
            self.dispatch("9")

    def test_a_cancelled_dispatch_frees_the_product_again(self):
        d = self.dispatch("5")
        record_event(d, EventType.CANCELLED)
        self.assertEqual(available_to_dispatch(self.grid, self.pellets), Decimal("8"))

    def test_creation_goes_to_the_ledger_with_the_hub(self):
        d = self.dispatch()
        self.assertEqual(d.hub, self.hub)
        self.assertEqual(d.code, "DSP-000001")
        self.assertEqual([e.entry_type for e in entries_for(d)], ["dispatch.created"])

    def test_the_journey_is_recorded_step_by_step_with_weights(self):
        d = self.deliver(self.dispatch("5"), "4.9", "4.8")
        self.assertEqual(d.stage, DispatchStage.DELIVERED)
        self.assertEqual(d.current_quantity_tonnes, Decimal("4.8"))
        self.assertEqual(d.loss_tonnes, Decimal("0.2"))
        self.assertEqual(
            [e.entry_type for e in entries_for(d)],
            ["dispatch.created", "dispatch.received_at_hub", "dispatch.in_transit", "dispatch.delivered"],
        )
        self.assertEqual(d.events.count(), 3)
        self.assertTrue(all(e.ledger_seq for e in d.events.all()))

    def test_a_lot_can_skip_the_hub(self):
        d = self.dispatch()
        record_event(d, EventType.IN_TRANSIT, quantity_tonnes=Decimal("5"))
        record_event(d, EventType.DELIVERED, quantity_tonnes=Decimal("5"))
        d.refresh_from_db()
        self.assertEqual(d.stage, DispatchStage.DELIVERED)

    def test_steps_must_follow_the_order(self):
        d = self.dispatch()
        with self.assertRaises(ValidationError):
            record_event(d, EventType.DELIVERED, quantity_tonnes=Decimal("5"))

    def test_a_lot_cannot_gain_weight(self):
        d = self.dispatch("5")
        with self.assertRaises(ValidationError) as caught:
            record_event(d, EventType.RECEIVED_AT_HUB, quantity_tonnes=Decimal("5.5"))
        self.assertIn("gain weight", str(caught.exception))

    def test_a_weight_is_needed_except_when_cancelling(self):
        d = self.dispatch()
        with self.assertRaises(ValidationError):
            record_event(d, EventType.RECEIVED_AT_HUB)

    def test_nothing_happens_after_delivery_or_cancellation(self):
        d = self.deliver(self.dispatch())
        with self.assertRaises(ValidationError):
            record_event(d, EventType.CANCELLED)

    def test_requirement_must_match_factory_and_product(self):
        from apps.demand.models import Requirement

        other = make_factory(self.factory_site.buyer, name="Other plant")
        requirement = Requirement.objects.create(
            factory=other, product=self.pellets, volume_tonnes=10, needed_from=date(2026, 1, 1), needed_by=date(2026, 2, 1)
        )
        with self.assertRaises(ValidationError):
            create_dispatch(
                grid=self.grid, product=self.pellets, factory=self.factory_site, quantity_tonnes=Decimal("1"), requirement=requirement
            )


class SaleTests(TradeTestCase):
    def delivered(self):
        return self.deliver(self.dispatch("5"))

    def test_flat_fee_sale_splits_the_money_three_ways(self):
        self.schedule()
        sale = record_sale(self.delivered(), sale_value=Decimal("20000"), farmer_payment=Decimal("7200"))
        self.assertEqual(sale.platform_fee, Decimal("960.00"))  # 4.8 t x Rs 200
        self.assertEqual(sale.farmer_payment, Decimal("7200.00"))
        self.assertEqual(sale.mitra_margin, Decimal("11840.00"))
        self.assertEqual(sale.sale_value, sale.farmer_payment + sale.platform_fee + sale.mitra_margin)
        self.assertFalse(sale.farmer_payment_estimated)
        self.assertEqual(sale.code, "TXN-000001")

    def test_percentage_fee_sale(self):
        self.schedule(FeeModel.PERCENTAGE, percentage=Decimal("10"))
        sale = record_sale(self.delivered(), sale_value=Decimal("20000"), farmer_payment=Decimal("7000"))
        self.assertEqual(sale.platform_fee, Decimal("2000.00"))
        self.assertEqual(sale.mitra_margin, Decimal("11000.00"))

    def test_lease_sale_has_no_per_sale_fee(self):
        self.schedule(FeeModel.LEASE, lease_rupees_per_month=Decimal("25000"))
        sale = record_sale(self.delivered(), sale_value=Decimal("20000"), farmer_payment=Decimal("7000"))
        self.assertEqual(sale.platform_fee, Decimal("0.00"))
        self.assertEqual(sale.mitra_margin, Decimal("13000.00"))

    def test_farmer_payment_defaults_to_the_grids_average_pickup_price(self):
        self.schedule()
        sale = record_sale(self.delivered(), sale_value=Decimal("20000"))
        self.assertEqual(sale.farmer_payment, Decimal("7200.00"))  # Rs 1,500 x 4.8 t
        self.assertTrue(sale.farmer_payment_estimated)

    def test_farmer_payment_must_be_typed_when_there_are_no_pickups(self):
        self.schedule()
        from apps.operations.models import CollectionRecord

        CollectionRecord.objects.update(status="inactive")
        with self.assertRaises(ValidationError):
            record_sale(self.delivered(), sale_value=Decimal("20000"))

    def test_sale_keeps_the_fee_figures_it_used(self):
        schedule = self.schedule()
        sale = record_sale(self.delivered(), sale_value=Decimal("20000"), farmer_payment=Decimal("7200"))
        schedule.flat_rupees_per_tonne = Decimal("999")
        schedule.save()
        sale.refresh_from_db()
        self.assertIn('"flat_rupees_per_tonne":"200.00"', sale.fee_parameters)
        self.assertEqual(sale.platform_fee, Decimal("960.00"))

    def test_no_fee_schedule_means_no_sale(self):
        with self.assertRaises(ValidationError) as caught:
            record_sale(self.delivered(), sale_value=Decimal("1"), farmer_payment=Decimal("1"))
        self.assertIn("fee schedule", str(caught.exception))

    def test_only_delivered_lots_can_be_sold_and_only_once(self):
        self.schedule()
        with self.assertRaises(ValidationError):
            record_sale(self.dispatch(), sale_value=Decimal("1"), farmer_payment=Decimal("1"))
        d = self.delivered()
        record_sale(d, sale_value=Decimal("100"), farmer_payment=Decimal("1"))
        with self.assertRaises(ValidationError):
            record_sale(d, sale_value=Decimal("100"), farmer_payment=Decimal("1"))

    def test_payment_flow_is_recorded_in_order_in_the_ledger(self):
        self.schedule()
        sale = record_sale(self.delivered(), sale_value=Decimal("20000"), farmer_payment=Decimal("7200"))
        with self.assertRaises(ValidationError):
            mark_mitra_settled(sale)  # buyer has not paid yet
        mark_buyer_paid(sale, reference="UTR123")
        with self.assertRaises(ValidationError):
            mark_buyer_paid(sale)
        mark_mitra_settled(sale)
        sale.refresh_from_db()
        self.assertEqual(sale.buyer_payment, BuyerPayment.RECEIVED)
        self.assertEqual(
            [e.entry_type for e in entries_for(sale)], ["sale.recorded", "payment.received", "settlement.paid"]
        )

    def test_sale_ledger_entry_holds_the_three_way_split(self):
        self.schedule()
        sale = record_sale(self.delivered(), sale_value=Decimal("20000"), farmer_payment=Decimal("7200"))
        text = entries_for(sale).get().payload_text
        for expected in ('"farmer_payment":"7200.00"', '"platform_fee":"960.00"', '"mitra_margin":"11840.00"'):
            self.assertIn(expected, text)

    def test_the_whole_chain_still_verifies(self):
        self.schedule()
        record_sale(self.deliver(self.dispatch("5")), sale_value=Decimal("20000"), farmer_payment=Decimal("7200"))
        result = verify()
        self.assertTrue(result.ok, result.problem)
        self.assertGreaterEqual(LedgerEntry.objects.count(), 5)


class LeaseTests(TradeTestCase):
    def test_a_month_is_charged_once_and_goes_to_the_ledger(self):
        self.schedule(FeeModel.LEASE, lease_rupees_per_month=Decimal("25000"))
        charge = charge_lease(self.grid, date(2026, 3, 17))
        self.assertEqual(charge.period_start, date(2026, 3, 1))
        self.assertEqual(charge.amount, Decimal("25000.00"))
        self.assertEqual([e.entry_type for e in entries_for(charge)], ["lease.charged"])
        with self.assertRaises(ValidationError):
            charge_lease(self.grid, date(2026, 3, 30))

    def test_only_lease_regions_are_charged(self):
        self.schedule()
        with self.assertRaises(ValidationError):
            charge_lease(self.grid, date(2026, 3, 1))
        self.assertEqual(LeaseCharge.objects.count(), 0)
