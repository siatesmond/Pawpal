from django.test import TestCase
from django.utils import timezone

from core.models import Outlet

from inventory.models import Brand, CartItem, Category, Order, Product
from payment.models import PointsTransaction
from user.models import Customer


class CheckoutSuccessTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            username="customer",
            email="customer@example.com",
            password="password",
        )
        self.order = Order.objects.create(
            customer=self.customer,
            subtotal_cents=1000,
            total_cents=1000,
        )

    def test_checkout_success_uses_custom_session_authentication(self):
        session = self.client.session
        session["user_id"] = self.customer.pk
        session["user_type"] = "customer"
        session["checkout_order_id"] = self.order.pk
        session.save()

        response = self.client.get("/payment/checkout/success/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["order"], self.order)

    def test_checkout_success_without_recent_order_redirects_home(self):
        session = self.client.session
        session["user_id"] = self.customer.pk
        session["user_type"] = "customer"
        session.save()

        response = self.client.get("/payment/checkout/success/")

        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_apply_points_renders_updated_totals_without_ordering(self):
        category = Category.objects.create(name="Food")
        brand = Brand.objects.create(name="Brand")
        product = Product.objects.create(
            category=category,
            brand=brand,
            name="Dog food",
            pet_type=Product.PetType.DOG,
            description="Food",
            price_cents=5000,
            stock_quantity=5,
        )
        CartItem.objects.create(customer=self.customer, product=product, quantity=1)
        PointsTransaction.objects.create(
            customer=self.customer,
            points=100,
            transaction_type=PointsTransaction.Type.EARNED,
            reason="Test points",
        )

        session = self.client.session
        session["user_id"] = self.customer.pk
        session["user_type"] = "customer"
        session.save()

        response = self.client.post(
            "/payment/checkout/",
            {
                "action": "preview_points",
                "points_to_redeem": "100",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["points_discount_dollars"], 1)
        self.assertEqual(response.context["total_dollars"], 49)
        self.assertEqual(Order.objects.count(), 1)

    def test_redeeming_more_points_than_subtotal_only_deducts_points_used(self):
        category = Category.objects.create(name="Toys")
        brand = Brand.objects.create(name="Brand")
        product = Product.objects.create(
            category=category,
            brand=brand,
            name="Chew toy",
            pet_type=Product.PetType.DOG,
            description="Toy",
            price_cents=1000,
            stock_quantity=5,
        )
        CartItem.objects.create(customer=self.customer, product=product, quantity=1)
        PointsTransaction.objects.create(
            customer=self.customer,
            points=5000,
            transaction_type=PointsTransaction.Type.EARNED,
            reason="Test points",
        )
        outlet = Outlet.objects.create(
            name="Main",
            address="1 Street",
            postal_code="123456",
            phone="61234567",
            opening_time=timezone.now(),
            closing_time=timezone.now(),
            is_active=True,
        )

        session = self.client.session
        session["user_id"] = self.customer.pk
        session["user_type"] = "customer"
        session.save()

        response = self.client.post(
            "/payment/checkout/",
            {
                "delivery_method": "pickup",
                "pickup_outlet": outlet.pk,
                "points_to_redeem": "5000",
                "payment_method": "CARD",
                "card_number": "1234567812345678",
                "expiry": "12/30",
                "cvv": "123",
            },
        )

        self.assertRedirects(response, "/payment/checkout/success/", fetch_redirect_response=False)
        redeemed = PointsTransaction.objects.get(
            customer=self.customer,
            transaction_type=PointsTransaction.Type.REDEEMED,
        )
        self.assertEqual(redeemed.points, -1000)
        balance = sum(t.points for t in self.customer.points_transactions.all())
        self.assertEqual(balance, 4000)
        # Shared record_payment() keeps only the last 4 card digits
        self.assertEqual(redeemed.payment.card_number, "**** 5678")


class CheckoutFormPointsTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            username="pointsuser",
            email="points@example.com",
            password="password",
        )

    def _form(self, points, balance):
        from payment.forms import CheckoutForm

        return CheckoutForm(
            self.customer,
            {"delivery_method": "pickup", "points_to_redeem": str(points)},
            points_balance=balance,
        )

    def test_redeeming_more_than_balance_is_rejected(self):
        form = self._form(150, balance=100)
        form.is_valid()
        self.assertIn(
            "You only have 100 points available.",
            form.errors["points_to_redeem"],
        )

    def test_redeeming_within_balance_has_no_points_error(self):
        form = self._form(100, balance=100)
        form.is_valid()
        self.assertNotIn("points_to_redeem", form.errors)

    def test_zero_balance_disables_field_and_ignores_submitted_points(self):
        form = self._form(500, balance=0)
        form.is_valid()
        self.assertTrue(form.fields["points_to_redeem"].disabled)
        self.assertNotIn("points_to_redeem", form.errors)
        self.assertIsNone(form.cleaned_data.get("points_to_redeem"))


class PreviewPointsTests(TestCase):
    def test_preview_points_does_not_show_validation_errors(self):
        customer = Customer.objects.create(
            username="previewer", email="preview@example.com", password="password"
        )
        PointsTransaction.objects.create(
            customer=customer,
            points=100,
            transaction_type=PointsTransaction.Type.EARNED,
            reason="Test points",
        )
        session = self.client.session
        session["user_id"] = customer.pk
        session["user_type"] = "customer"
        session.save()

        response = self.client.post(
            "/payment/checkout/",
            {"action": "preview_points", "points_to_redeem": "50", "delivery_method": "pickup"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "This field is required")
        self.assertNotContains(response, "Select a pick-up outlet")
        # The user's input is kept on the re-rendered form
        form = response.context["form"]
        self.assertFalse(form.is_bound)
        self.assertEqual(form.initial["points_to_redeem"], "50")
        self.assertContains(response, 'value="50"')
        self.assertEqual(form["delivery_method"].value(), "pickup")
        self.assertRegex(
            response.content.decode(),
            r'<input type="radio" name="delivery_method" value="pickup"[^>]*checked',
        )


class PaymentDetailsFormTests(TestCase):
    def test_expired_card_is_rejected(self):
        from payment.forms import PaymentDetailsForm

        customer = Customer.objects.create(
            username="carduser", email="card@example.com", password="password"
        )
        form = PaymentDetailsForm(
            customer,
            {"payment_method": "CARD", "card_number": "1234567812345678",
             "expiry": "01/20", "cvv": "123"},
            points_balance=0,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("This card has expired.", form.errors["expiry"])
