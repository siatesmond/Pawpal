from datetime import timedelta

from django.db.models import F, Sum
from django.utils import timezone

from .models import Payment, PointsTransaction

POINTS_PER_DOLLAR = 10  # points earned for each whole dollar paid
CANCEL_WINDOW = timedelta(hours=24)  # customers can cancel within 24 hours of booking / ordering

# Checkout logic shared by both shop products checkout and book service checkout.

# Both checkouts process flows are similar
#   1. Show a PaymentDetailsForm (points + card) next to a order/booking summary.
#   2. "Apply points" re-renders the page with the discount, without validating.
#   3. "Place order" validates, then the view creates its Order or Booking
#      and calls record_payment() inside a transaction.

# Customer's current points (sum of all their points transactions) 
def get_points_balance(customer):
    return customer.points_transactions.aggregate(total=Sum("points"))["total"] or 0


# Give or take points. Always use this instead of creating a PointsTransaction
# directly: it saves the history row AND updates customer.point_balance,
# so the profile, home page and navbar always show the same number.
def add_points(customer, points, transaction_type, reason, payment=None):
    PointsTransaction.objects.create(
        customer=customer,
        points=points,
        transaction_type=transaction_type,
        payment=payment,
        reason=reason,
    )
    # F() adds to the number already in the database (safe if two things happen at once)
    type(customer).objects.filter(pk=customer.pk).update(point_balance=F("point_balance") + points)
    customer.refresh_from_db(fields=["point_balance"])


# Calculate the discount in cents for a given subtotal and points to redeem.
# 1 point = 1 cent 
def calculate_points_discount(subtotal_cents, points_to_redeem, points_balance):
    if not points_to_redeem or points_to_redeem <= 0:
        return 0
    return min(points_to_redeem, points_balance, subtotal_cents) # discount cannot exceed subtotal or points balance

# Error shown when a customer inputs more points than they have
def points_limit_message(points_balance):
    return f"You only have {points_balance} points available."

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

# Payment summary for booking/order detail pages in profile
def payment_summary(record, subtotal_cents):
    return {
        "subtotal_dollars": subtotal_cents / 100,
        "discount_dollars": record.points_discount_cents / 100,
        "points_used": record.points_discount_cents,  # 1 point = 1 cent
        "total_dollars": record.total_cents / 100,
        "points_earned": points_earned(record.total_cents),
        "payment": record.payments.order_by("-created_at").first(),  # latest payment
    }

# Builds checkout form, called by both shop and service-booking checkouts
# Returns (form, preview_points).
def bind_checkout_form(request, form_class, customer, points_balance, **form_kwargs):

    # GET Empty form when the page is first loaded
    if request.method != "POST":
        preview_points = 0 
        return form_class(customer, points_balance=points_balance, **form_kwargs), preview_points

    # Place order / Place booking was clicked: bound form, so the view can call is_valid()
    if request.POST.get("action") == "place_order":
        preview_points = 0  # not previewing; the view works out the real discount after validating
        return form_class(customer, request.POST, points_balance=points_balance, **form_kwargs), preview_points

    # Apply points button was clicked, re-render the page with the discount applied
    if request.POST.get("action") == "preview_points":
        form = form_class(
            customer, initial=request.POST.dict(), points_balance=points_balance, **form_kwargs
        )
        try:
            preview_points = int(request.POST.get("points_to_redeem") or 0)
        except (TypeError, ValueError):
            preview_points = 0

        # Points field is validated on preview, the rest waits for "Place order" button to be clciked
        # More than available points: show the error, but the summary still previews the discount capped at balance
        error = None
        if preview_points < 0:
            error = "Enter 0 or more points."
        elif preview_points > points_balance:
            error = points_limit_message(points_balance)
        if error:
            form.cleaned_data = {}  # an unbound form has no cleaned_data, which add_error() needs
            form.add_error("points_to_redeem", error)
        return form, preview_points

    # Any other POST (no recognised button): just show the page again, nothing saved
    preview_points = 0
    return form_class(customer, points_balance=points_balance, **form_kwargs), preview_points


# Create and save the payment and any points transactions (earned or redeemed) for an order or booking
def record_payment(customer, form, *, amount_cents, points_redeemed, label, order=None, booking=None, sitting_request=None):

    payment = Payment.objects.create(
        customer=customer,
        order=order,
        booking=booking,
        sitting_request=sitting_request,  # pet sitting payment
        amount_cents=amount_cents,
        method=form.cleaned_data["payment_method"],
        card_number=f"**** {form.cleaned_data['card_number'][-4:]}",  # only keep the last 4 digits
        status=Payment.Status.COMPLETED,
    )

    # REDEEMED must be negative (check constraint on PointsTransaction)
    if points_redeemed > 0:
        add_points(customer, -points_redeemed, PointsTransaction.Type.REDEEMED, f"Redeemed on {label}", payment)

    earned = points_earned(amount_cents)
    if earned > 0:
        add_points(customer, earned, PointsTransaction.Type.EARNED, f"Earned from {label}", payment)
    return payment


# Cancel booking or order

def cancel_deadline(record):
    return record.created_at + CANCEL_WINDOW


# Booking and Order status must have PENDING / CONFIRMED 
# A record can be cancelled only before staff start on it and within 24 hours after created
def can_cancel(record):
    not_started = record.status in (record.Status.PENDING, record.Status.CONFIRMED)
    return not_started and timezone.now() <= cancel_deadline(record)


# Refund a cancelled Booking or Order (called by cancel booking/order views)
def refund_payment(record, label):

    #  Update status to Refunded for completed payments
    for payment in record.payments.filter(status=Payment.Status.COMPLETED):
        payment.status = Payment.Status.REFUNDED
        payment.save(update_fields=["status"])

        # Calculate points redeemed and earned for this payment
        redeemed = -sum(
            t.points for t in payment.points_transactions.all()
            if t.transaction_type == PointsTransaction.Type.REDEEMED
        )
        earned = sum(
            t.points for t in payment.points_transactions.all()
            if t.transaction_type == PointsTransaction.Type.EARNED
        )
        # Reverse points transactions for the payment
        # Refund points that were redeemed
        if redeemed > 0:
            add_points(payment.customer, redeemed, PointsTransaction.Type.REFUNDED, f"Points returned for cancelled {label}", payment)

        # Remove points that were earned (status - redeemed)
        # but never more than the customer still has (they may have spent some already)
        earned = min(earned, payment.customer.point_balance)
        if earned > 0:
            add_points(payment.customer, -earned, PointsTransaction.Type.REDEEMED, f"Earned points removed for cancelled {label}", payment)
