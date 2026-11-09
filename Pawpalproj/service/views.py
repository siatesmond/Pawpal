import calendar
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.db import transaction
from django.db.models import F, Min
from django.shortcuts import HttpResponse, get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.models import Outlet
from payment.forms import PaymentDetailsForm

# Shard services for booking and payment
from payment.services import (
    bind_checkout_form,
    calculate_points_discount,
    checkout_totals,
    get_points_balance,
    points_earned,
    record_payment,
)
from user.models import Customer

from .models import Booking, Service, TimeSlot

services = [
    {
        "name": "Dog Grooming",
        "category": "GROOMING",
        "description": "Bath, blow-dry, haircut, nail trim and ear cleaning for dogs.",
        "duration_minutes": 90,
        "price_cents": 6500,
    },
    {
        "name": "Cat Grooming",
        "category": "GROOMING",
        "description": "Gentle bath, brush-out, nail trim and ear cleaning for cats.",
        "duration_minutes": 60,
        "price_cents": 5500,
    },
    {
        "name": "Overnight Boarding",
        "category": "BOARDING",
        "description": "Comfortable private suite with daily walks and playtime. Priced per night.",
        "duration_minutes": None,
        "price_cents": 8000,
    },
    {
        "name": "Daycare (Half Day)",
        "category": "DAYCARE",
        "description": "Up to 5 hours of supervised play and rest.",
        "duration_minutes": 300,
        "price_cents": 3500,
    },
    {
        "name": "Daycare (Full Day)",
        "category": "DAYCARE",
        "description": "Up to 10 hours of supervised play, meals and rest.",
        "duration_minutes": 600,
        "price_cents": 6000,
    },
    {
        "name": "Basic Obedience Training",
        "category": "OTHER",
        "description": "One-hour private session covering sit, stay, recall and loose-lead walking.",
        "duration_minutes": 60,
        "price_cents": 9000,
    },
]

def loadData(request):

    Booking.objects.all().delete()
    TimeSlot.objects.all().delete()
    Service.objects.all().delete()

    # Load services
    for service in services:
        new_service = Service(
            name=service["name"],
            category=service["category"],
            description=service["description"],
            duration_minutes=service["duration_minutes"],
            price_cents=service["price_cents"],
        )

        new_service.save()

    return HttpResponse("Data loaded successfully into the database.")


# Views
SGT = ZoneInfo("Asia/Singapore")
MAX_NIGHTS = 14  # longest boarding stay


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_boarding(service):
    return service.category == Service.Category.BOARDING

# Find all open time slots for a given outlet and service (with capacity left)
def _open_slots(outlet, service):
    return TimeSlot.objects.filter(
        outlet=outlet,
        service=service,
        start_time__gt=timezone.now(),
        capacity__gt=F("booked_count"),  # still has space
    )

# Validate the pet, service, outlet, slot and nights from the session or GET params, 
# returns a dict of them including the calculated price and check-out date (if boarding). 
# (None if there was an error.)
def _validate_selection(customer, pet_id, service_id, outlet_id, slot_id, nights):
    pet = customer.pets.filter(pk=_to_int(pet_id)).first()
    service = Service.objects.filter(pk=_to_int(service_id), is_active=True).first()
    outlet = Outlet.objects.filter(pk=_to_int(outlet_id), is_active=True).first()
    if not (pet and service and outlet):
        return None, "Please choose a pet, service and outlet."

    slot = _open_slots(outlet, service).filter(pk=_to_int(slot_id)).first()
    if slot is None:
        return None, "Sorry, that time is no longer available. Please pick another."

    nights = min(max(_to_int(nights, 1), 1), MAX_NIGHTS) if _is_boarding(service) else 1
    price_cents = service.price_cents * nights
    day = slot.start_time.astimezone(SGT).date()

    return {
        "pet": pet,
        "service": service,
        "outlet": outlet,
        "slot": slot,
        "day": day,
        "start": slot.start_time,
        "nights": nights,
        "check_out_date": day + timedelta(days=nights) if _is_boarding(service) else None,
        "check_out_time": slot.end_time,
        "price_cents": price_cents,
    }, None


def _selection_params(source):
    """Query-string params that recreate a selection on the booking page."""
    keys = ["pet", "service", "outlet", "date", "slot", "nights"]
    return urlencode({k: source[k] for k in keys if source.get(k) not in (None, "")})


def _format_day(d):
    return f"{d:%a} {d.day} {d:%b}"  # e.g. "Fri 16 Oct"


def _format_start(start):
    return f"{_format_day(start.astimezone(SGT))}, {start.astimezone(SGT):%H:%M}"


def _format_check_out(check_out_date, end_time):
    return f"{_format_day(check_out_date)}, {end_time.astimezone(SGT):%H:%M}"


# Booking summary: pet, service, outlet, when, nights, check-out, price.
# Full price (points only applied at checkout) and check-out only if a slot is chosen.
def _summary(selection):

    price = selection.get("price_cents")
    start = selection.get("start")
    check_out = selection.get("check_out_date")
    return {
        "pet": selection.get("pet"),
        "service": selection.get("service"),
        "outlet": selection.get("outlet"),
        "when": _format_start(start) if start else None,
        "nights": selection.get("nights"),
        "check_out": _format_check_out(check_out, selection["check_out_time"]) if check_out else None,
        "price_dollars": price / 100 if price is not None else None,
    }

# Get customer from session
def _require_customer(request):
    customer = None
    if "user_id" in request.session and request.session.get("user_type") == "customer":
        customer = Customer.objects.filter(pk=request.session["user_id"]).first()
    if customer is None:
        messages.error(request, "Please log in as a customer to book a service.")
    return customer


def book(request):
    customer = _require_customer(request)
    if customer is None:
        return redirect("user:login")

    # "Continue to checkout": validate, stash the choice in the session, and redirect to checkout page
    if request.method == "POST":
        data = request.POST
        selection, error = _validate_selection (
            customer,
            data.get("pet"), data.get("service"), data.get("outlet"),
            data.get("slot"), data.get("nights"),
        )
        if error:
            messages.error(request, error)
            return redirect(f"{reverse('service:book')}?{_selection_params(data)}")
        
        # Stash the selection in the session so it can be used in the checkout view
        request.session["pending_booking"] = {
            "pet": selection["pet"].pk,
            "service": selection["service"].pk,
            "outlet": selection["outlet"].pk,
            "date": selection["day"].isoformat(),
            "slot": selection["slot"].pk,
            "nights": selection["nights"],
        }
        return redirect("service:book_checkout")

    # Everything below rebuilds the page from the GET params
    params = request.GET
    today = timezone.now().astimezone(SGT).date()

    pets = list(customer.pets.all())
    pet = next((p for p in pets if p.pk == _to_int(params.get("pet"))), pets[0] if pets else None)

    # Service cards: one per Service.Category, priced from the cheapest active service
    min_prices = dict(
        Service.objects.filter(is_active=True)
        .values_list("category")
        .annotate(Min("price_cents"))
    )
    category_cards = [
        {
            "value": value,
            "label": label,
            "initial": label[0],
            "unit": "night" if value == Service.Category.BOARDING else "",
            "from_dollars": min_prices[value] / 100 if value in min_prices else None,
        }
        for value, label in Service.Category.choices
    ]

    service = Service.objects.filter(pk=_to_int(params.get("service")), is_active=True).first()
    category = params.get("category")
    if category not in min_prices:
        category = service.category if service else next(
            (value for value, _ in Service.Category.choices if value in min_prices), None
        )
    packages = list(Service.objects.filter(is_active=True, category=category).order_by("price_cents"))
    if service not in packages:
        service = packages[0] if packages else None
    for s in packages:
        s.price_dollars = s.price_cents / 100

    outlets = list(Outlet.objects.filter(is_active=True).order_by("name"))
    outlet = next((o for o in outlets if o.pk == _to_int(params.get("outlet"))), outlets[0] if outlets else None)

    nights = min(max(_to_int(params.get("nights"), 1), 1), MAX_NIGHTS)

    # Days that have at least one open TimeSlot for this outlet and service
    open_days = sorted({
        start.astimezone(SGT).date()
        for start in (
            _open_slots(outlet, service).values_list("start_time", flat=True)
            if service and outlet else []
        )
    })

    # Selected day: from params, otherwise the first day with an open slot
    try:
        day = date.fromisoformat(params.get("date"))
    except (TypeError, ValueError):
        day = None
    if day is None or day < today:
        day = open_days[0] if open_days else today

    # All TimeSlots for the selected day, including full ones (shown greyed out)
    slots = []
    if service and outlet:
        day_start = datetime.combine(day, time.min, tzinfo=SGT)
        now = timezone.now()
        for s in TimeSlot.objects.filter(
            outlet=outlet,
            service=service,
            start_time__gte=day_start,
            start_time__lt=day_start + timedelta(days=1),
        ).order_by("start_time"):
            s.time = s.start_time.astimezone(SGT).strftime("%H:%M")
            s.left = max(s.capacity - s.booked_count, 0)
            s.past = s.start_time <= now
            s.available = s.capacity > s.booked_count and not s.past
            slots.append(s)
    slot = next((s for s in slots if s.pk == _to_int(params.get("slot")) and s.available), None)

    # Calendar: any day from today can be picked; days with open slots get a dot
    first_month = today.replace(day=1)
    month_start = None
    for raw in (params.get("nav"), params.get("month")):  # arrows send "nav"
        try:
            month_start = datetime.strptime(raw, "%Y-%m").date()
            break
        except (TypeError, ValueError):
            continue
    month_start = month_start or day.replace(day=1)
    month_start = max(month_start, first_month)

    open_day_set = set(open_days)
    weeks = [
        [
            {
                "date": d,
                "in_month": d.month == month_start.month,
                "disabled": d < today,
                "has_slots": d in open_day_set,
                "selected": d == day,
                "today": d == today,
            }
            for d in week
        ]
        for week in calendar.Calendar(firstweekday=0).monthdatescalendar(month_start.year, month_start.month)
    ]
    prev_month = (month_start - timedelta(days=1)).replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)

    # Booking summary: full details once a time is picked, partial otherwise
    selection = None
    if pet and service and outlet and slot:
        selection, _ = _validate_selection(customer, pet.pk, service.pk, outlet.pk, slot.pk, nights)
    if selection is None:
        price_cents = service.price_cents * (nights if _is_boarding(service) else 1) if service else None
        selection = {
            "pet": pet, "service": service, "outlet": outlet,
            "nights": nights if service and _is_boarding(service) else None,
            "price_cents": price_cents,
        }

    context = {
        "step": 2 if pet and service else 1,
        "pets": pets,
        "pet": pet,
        "category_cards": category_cards,
        "category": category,
        "category_label": Service.Category(category).label if category else "Service",
        "packages": packages,
        "service": service,
        "is_boarding": bool(service and _is_boarding(service)),
        "nights": nights,
        "nights_range": range(1, MAX_NIGHTS + 1),
        "outlets": outlets,
        "outlet": outlet,
        "day": day,
        "day_label": _format_day(day),
        "slots": slots,
        "slot": slot,
        "month_start": month_start,
        "weeks": weeks,
        "weekday_names": ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"],
        "prev_month": prev_month if prev_month >= first_month else None,
        "next_month": next_month,
        "has_open_days": bool(open_days),
        "summary": _summary(selection),
        "ready": bool(pet and service and outlet and slot),
    }
    return render(request, "service/book.html", context)

# Ceckout for the chosen booking: points + payment, same as the shop checkout
def book_checkout(request):
    customer = _require_customer(request)
    if customer is None:
        return redirect("user:login")

   # Get the selected booking from the session,
   # redirect back to the booking page if not found
    pending = request.session.get("pending_booking")
    if not pending:
        messages.error(request, "Please choose a service and time first.")
        return redirect("service:book")

    edit_url = f"{reverse('service:book')}?{_selection_params(pending)}"

    def back_to_booking(error):
        messages.error(request, error)
        return redirect(edit_url)

    selection, error = _validate_selection(
        customer,
        pending["pet"], pending["service"], pending["outlet"],
        pending["slot"], pending["nights"],
    )
    if error:
        return back_to_booking(error)

    price_cents = selection["price_cents"]
    points_balance = get_points_balance(customer)
    form, preview_points = bind_checkout_form(request, PaymentDetailsForm, customer, points_balance)

    # preview_points is None only for "Place booking"
    if preview_points is None and form.is_valid():
        with transaction.atomic():
            # Lock the slot row (only if it still has space) so two customers can't take the last slot
            slot = (
                TimeSlot.objects.select_for_update()
                .filter(pk=selection["slot"].pk, capacity__gt=F("booked_count"))
                .first()
            )
            if slot is None:
                return back_to_booking("Sorry, that time was just taken. Please pick another.")

            # Re-check the balance inside the transaction so points can't be spent twice
            discount_cents = calculate_points_discount(
                price_cents,
                form.cleaned_data.get("points_to_redeem") or 0,
                get_points_balance(customer),
            )

            # Create the booking and increment the booked_count for the slot
            booking = Booking.objects.create(
                customer=customer,
                pet=selection["pet"],
                slot=slot,
                check_out_date=selection["check_out_date"],
                status=Booking.Status.CONFIRMED,
                price_cents=price_cents,
                points_discount_cents=discount_cents,
                total_cents=price_cents - discount_cents,
            )
            slot.booked_count += 1
            slot.save(update_fields=["booked_count"])

            # GET, "Apply points", or a failed "Place booking"
            record_payment(
                customer, form,
                amount_cents=booking.total_cents,
                points_redeemed=discount_cents,
                label=f"Booking #{booking.pk}",
                booking=booking,
            )

        # Clear the pending booking from the session 
        # and stash the last booking ID for the booking success page
        request.session.pop("pending_booking", None)
        request.session["last_booking_id"] = booking.pk
        return redirect("service:book_success")

    # Calculate the discount and totals for the summary
    discount_cents = calculate_points_discount(price_cents, preview_points, points_balance)

    return render(request, "service/book_checkout.html", {
        "step": 3,
        "form": form,
        "summary": _summary(selection),
        "summary_title": "Booking summary",
        "checkout_intro": "Use your points and pay by card to confirm your booking",
        "submit_text": "Place Booking",
        "back_url": edit_url,
        "back_text": "Edit booking",
        **checkout_totals(price_cents, discount_cents),
    })

# Booking success page: show the booking details and points earned
def book_success(request):
    customer = _require_customer(request)
    if customer is None:
        return redirect("user:login")

    booking_id = request.session.pop("last_booking_id", None)
    if booking_id is None:
        return redirect("service:book")

    # Show the booking details, points earned, and total paid from db
    booking = get_object_or_404(
        Booking.objects.select_related("pet", "slot__service", "slot__outlet"),
        pk=booking_id,
        customer=customer,
    )
    
    return render(request, "service/book_success.html", {
        "booking": booking,
        "when": _format_start(booking.slot.start_time),
        "check_out": (
            _format_check_out(booking.check_out_date, booking.slot.end_time)
            if booking.check_out_date else None
        ),
        "total_dollars": booking.total_cents / 100,
        "discount_dollars": booking.points_discount_cents / 100,
        "points_earned": points_earned(booking.total_cents),
    })
