from django.db.models import Sum

from .models import Payment, PointsTransaction

POINTS_PER_DOLLAR = 10  # points earned for each whole dollar paid

# Checkout logic shared by both shop products checkout and book service checkout.

# Both checkouts process flows are similar
#   1. Show a PaymentDetailsForm (points + card) next to a order/booking summary.
#   2. "Apply points" re-renders the page with the discount, without validating.
#   3. "Place order" validates, then the view creates its Order or Booking
#      and calls record_payment() inside a transaction.

# Customer's current points (sum of all their points transactions) 
def get_points_balance(customer):
    return customer.points_transactions.aggregate(total=Sum("points"))["total"] or 0


# Calculate the discount in cents for a given subtotal and points to redeem.
# 1 point = 1 cent (ensures that customer don't redeem more than the points balance or the amount being paid)
def calculate_points_discount(subtotal_cents, points_to_redeem, points_balance):
    if not points_to_redeem or points_to_redeem <= 0:
        return 0
    return min(points_to_redeem, points_balance, subtotal_cents)

# Calculate the points earned for the total payable in cents
def points_earned(total_cents):
    return (total_cents // 100) * POINTS_PER_DOLLAR

# For displaying the checkout summary, calculate subtotal, discount, total, and points earned
def checkout_totals(subtotal_cents, points_discount_cents=0):
    total_cents = subtotal_cents - points_discount_cents
    return {
        "subtotal_dollars": subtotal_cents / 100,
        "points_discount_dollars": points_discount_cents / 100,
        "total_dollars": total_cents / 100,
        "points_earned": points_earned(total_cents),
    }


def bind_checkout_form(request, form_class, customer, points_balance, **form_kwargs):
    """Build the checkout form for this request.

    Returns (form, preview_points):
      - GET: empty form, preview_points = 0
      - POST "Apply points": unbound form pre-filled with what was typed, so
        fields not filled in yet don't show "This field is required";
        preview_points is the number typed in the points box
      - POST "Place order": bound form, ready for form.is_valid();
        preview_points = None
    """
    if request.method != "POST":
        return form_class(customer, points_balance=points_balance, **form_kwargs), 0

    if request.POST.get("action") == "preview_points":
        form = form_class(
            customer, initial=request.POST.dict(), points_balance=points_balance, **form_kwargs
        )
        try:
            preview_points = int(request.POST.get("points_to_redeem") or 0)
        except (TypeError, ValueError):
            preview_points = 0
        return form, preview_points

    return form_class(customer, request.POST, points_balance=points_balance, **form_kwargs), None


# Create and save the payment and any points transactions (earned or redeemed) for an order or booking
def record_payment(customer, form, *, amount_cents, points_redeemed, label, order=None, booking=None):

    payment = Payment.objects.create(
        customer=customer,
        order=order,
        booking=booking,
        amount_cents=amount_cents,
        method=form.cleaned_data["payment_method"],
        card_number=f"**** {form.cleaned_data['card_number'][-4:]}",  # only keep the last 4 digits
        status=Payment.Status.COMPLETED,
    )

    # REDEEMED must be negative (check constraint on PointsTransaction)
    if points_redeemed > 0:
        PointsTransaction.objects.create(
            customer=customer,
            points=-points_redeemed,
            transaction_type=PointsTransaction.Type.REDEEMED,
            payment=payment,
            reason=f"Redeemed on {label}",
        )

    earned = points_earned(amount_cents)
    if earned > 0:
        PointsTransaction.objects.create(
            customer=customer,
            points=earned,
            transaction_type=PointsTransaction.Type.EARNED,
            payment=payment,
            reason=f"Earned from {label}",
        )
    return payment
