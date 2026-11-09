from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Outlet
from payment.models import Payment, PointsTransaction
from user.models import Customer, Pet

from .models import Booking, Service, TimeSlot
from .views import SGT


class BookingTestBase(TestCase):
    """Shared customer, pet, outlet, services and time slot for booking tests."""

    def setUp(self):
        self.customer = Customer.objects.create(
            username="wei", email="wei@example.com", password="password"
        )
        self.pet = Pet.objects.create(
            name="Mochi", pet_type=Pet.PetType.DOG, breed="Shiba Inu", owner_id=self.customer
        )
        now = timezone.now()
        self.outlet = Outlet.objects.create(
            name="Tampines Outlet", address="1 Road", postal_code="123456", phone="61234567",
            opening_time=now, closing_time=now, is_active=True,
        )
        self.groom = Service.objects.create(
            name="Full groom", category=Service.Category.GROOMING,
            duration_minutes=90, price_cents=4500,
        )
        self.boarding = Service.objects.create(
            name="Overnight", category=Service.Category.BOARDING, price_cents=6000,
        )
        PointsTransaction.objects.create(
            customer=self.customer, points=1240,
            transaction_type=PointsTransaction.Type.EARNED, reason="Test",
        )
        # tomorrow is always in the future
        self.day = (timezone.now().astimezone(SGT) + timedelta(days=1)).date()
        self.slot = self.make_slot(self.groom, "11:30", capacity=2)

        session = self.client.session
        session["user_id"] = self.customer.pk
        session["user_type"] = "customer"
        session.save()

    def make_slot(self, service, hhmm, capacity=2, booked=0, end_hours=1):
        start = datetime.combine(self.day, time.fromisoformat(hhmm), tzinfo=SGT)
        return TimeSlot.objects.create(
            outlet=self.outlet, service=service, start_time=start,
            end_time=start + timedelta(hours=end_hours), capacity=capacity, booked_count=booked,
        )

    def choice(self, **overrides):
        data = {
            "pet": self.pet.pk, "service": self.groom.pk, "outlet": self.outlet.pk,
            "date": self.day.isoformat(), "slot": self.slot.pk, "nights": 1,
        }
        data.update(overrides)
        return data

    def card(self, **overrides):
        data = {
            "payment_method": "CARD", "card_number": "4111111111111111",
            "expiry": "12/99", "cvv": "123",
        }
        data.update(overrides)
        return data

    def pay(self, points=200, **overrides):
        """Step 2 "Continue to checkout", then "Place Booking" on the checkout page."""
        self.client.post("/service/book/", self.choice(**overrides))
        return self.client.post("/service/book/checkout/", self.card(points_to_redeem=points))



class BookingFlowTests(BookingTestBase):
    def test_requires_customer_login(self):
        self.client.session.flush()
        self.client.cookies.clear()
        response = self.client.get("/service/book/")
        self.assertRedirects(response, "/user/login/", fetch_redirect_response=False)

    def test_book_page_lists_timeslots_from_database(self):
        self.make_slot(self.groom, "14:00", capacity=3, booked=1)
        response = self.client.get("/service/book/", self.choice())
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s.time for s in response.context["slots"]], ["11:30", "14:00"])
        self.assertContains(response, "2 slots left")
        self.assertEqual(response.context["slot"], self.slot)
        self.assertTrue(response.context["ready"])

        # Points are chosen at checkout, so step 2 shows the full price
        self.assertEqual(response.context["summary"]["price_dollars"], 45)
        self.assertNotContains(response, 'name="points"')
        self.assertContains(response, "Mochi (Shiba Inu)")

    def test_categories_and_days_come_from_database(self):
        response = self.client.get("/service/book/")
        cards = {c["value"]: c["from_dollars"] for c in response.context["category_cards"]}
        self.assertEqual(cards["GROOMING"], 45)
        self.assertIsNone(cards["DAYCARE"])  # no daycare Service saved
        # defaults to the first day that has an open slot
        self.assertEqual(response.context["day"], self.day)

    def test_day_without_timeslots_shows_no_times(self):
        response = self.client.get(
            "/service/book/", self.choice(date=(self.day + timedelta(days=1)).isoformat(), slot="")
        )
        self.assertEqual(response.context["slots"], [])
        self.assertFalse(response.context["ready"])

    def test_full_slot_cannot_be_selected(self):
        self.slot.booked_count = 2
        self.slot.save()
        response = self.client.get("/service/book/", self.choice())
        self.assertIsNone(response.context["slot"])
        self.assertContains(response, "Full")

        self.client.post("/service/book/", self.choice())
        self.assertNotIn("pending_booking", self.client.session)

    def test_checkout_points_preview_is_capped_at_balance(self):
        self.client.post("/service/book/", self.choice())
        response = self.client.post("/service/book/checkout/", {
            "action": "preview_points", "points_to_redeem": "999999",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["points_discount_dollars"], 12.40)  # balance is 1240
        self.assertEqual(response.context["total_dollars"], 32.60)
        self.assertNotContains(response, "This field is required")  # preview doesn't validate
        self.assertFalse(Booking.objects.exists())

    def test_checkout_page_uses_shared_checkout_layout(self):
        self.client.post("/service/book/", self.choice())
        response = self.client.get("/service/book/checkout/")
        self.assertTemplateUsed(response, "payment/checkout_base.html")
        self.assertTemplateUsed(response, "payment/form_template.html")
        self.assertContains(response, "Booking summary")
        self.assertContains(response, "Place Booking")
        self.assertContains(response, "3&nbsp; Checkout")

    def test_redeeming_more_than_balance_is_rejected_at_checkout(self):
        response = self.pay(points=5000)  # balance is 1240
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You only have 1240 points available.")
        self.assertFalse(Booking.objects.exists())

    def test_expired_card_is_rejected(self):
        self.client.post("/service/book/", self.choice())
        response = self.client.post("/service/book/checkout/", self.card(expiry="01/20"))
        self.assertContains(response, "This card has expired.")
        self.assertFalse(Booking.objects.exists())

    def test_full_booking_creates_booking_payment_and_points(self):
        response = self.pay()
        self.assertRedirects(response, "/service/book/success/", fetch_redirect_response=False)

        booking = Booking.objects.get()
        self.assertEqual(booking.slot, self.slot)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.price_cents, 4500)
        self.assertEqual(booking.points_discount_cents, 200)
        self.assertEqual(booking.total_cents, 4300)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, 1)
        self.assertEqual(TimeSlot.objects.count(), 1)  # no slots created on the fly

        payment = Payment.objects.get(booking=booking)
        self.assertEqual(payment.amount_cents, 4300)
        self.assertEqual(payment.card_number, "**** 1111")
        new_points = payment.points_transactions.values_list("transaction_type", "points")
        self.assertCountEqual(new_points, [("REDEEMED", -200), ("EARNED", 430)])

        response = self.client.get("/service/book/success/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["booking"], booking)

    def test_boarding_charges_per_night(self):
        stay = self.make_slot(self.boarding, "14:00", capacity=5, end_hours=22)
        self.pay(points=0, service=self.boarding.pk, slot=stay.pk, nights=3)
        booking = Booking.objects.get()
        self.assertEqual(booking.price_cents, 18000)
        self.assertEqual(booking.check_out_date, self.day + timedelta(days=3))

    def test_slot_must_match_chosen_service(self):
        stay = self.make_slot(self.boarding, "14:00")
        self.client.post("/service/book/", self.choice(slot=stay.pk))  # groom + boarding slot
        self.assertNotIn("pending_booking", self.client.session)

    def test_last_place_cannot_be_double_booked(self):
        self.slot.capacity = 1
        self.slot.save()
        self.client.post("/service/book/", self.choice())  # chooses the last place
        self.slot.booked_count = 1  # someone else pays first
        self.slot.save()

        self.client.post("/service/book/checkout/", self.card())
        self.assertFalse(Booking.objects.exists())

    def test_cannot_book_another_customers_pet(self):
        other = Customer.objects.create(username="o", email="o@example.com", password="x")
        their_pet = Pet.objects.create(name="Kopi", pet_type=Pet.PetType.CAT, owner_id=other)
        self.client.post("/service/book/", self.choice(pet=their_pet.pk))
        self.assertNotIn("pending_booking", self.client.session)

    def test_any_future_day_is_clickable_and_open_days_are_marked(self):
        response = self.client.get("/service/book/", self.choice(slot=""))
        cells = {c["date"]: c for week in response.context["weeks"] for c in week}
        later = self.day + timedelta(days=1)
        if later in cells:  # same month
            self.assertFalse(cells[later]["disabled"])
            self.assertFalse(cells[later]["has_slots"])
        self.assertTrue(cells[self.day]["has_slots"])
        self.assertIsNotNone(response.context["next_month"])


class BookingPageWithoutJavaScriptTests(BookingTestBase):
    """The booking page works with plain form submits, no JavaScript."""

    def query(self, pairs):
        # Build a query string with repeated keys, the way a browser sends
        # a hidden input plus the clicked option button of the same name.
        from urllib.parse import urlencode
        return "/service/book/?" + urlencode(pairs)

    def test_page_has_no_javascript(self):
        response = self.client.get("/service/book/", self.choice())
        self.assertNotContains(response, "<script")

    def test_clicked_time_overrides_current_hidden_value(self):
        later = self.make_slot(self.groom, "15:00")
        base = [(k, v) for k, v in self.choice().items()]
        # Hidden input sends the current slot first, the clicked button sends the new one last
        response = self.client.get(self.query(base + [("slot", later.pk)]))
        self.assertEqual(response.context["slot"], later)

    def test_switching_category_picks_a_package_from_that_category(self):
        base = [(k, v) for k, v in self.choice().items()]
        response = self.client.get(self.query(base + [("category", Service.Category.BOARDING)]))
        self.assertEqual(response.context["service"], self.boarding)
        # The grooming time slot doesn't belong to boarding, so it is cleared
        self.assertIsNone(response.context["slot"])

    def test_option_buttons_render_as_submit_buttons(self):
        response = self.client.get("/service/book/", self.choice())
        self.assertContains(response, f'name="slot" value="{self.slot.pk}"')
        self.assertContains(response, 'class="slot is-selected"')
        self.assertContains(response, 'formaction="/service/book/#schedule"')
