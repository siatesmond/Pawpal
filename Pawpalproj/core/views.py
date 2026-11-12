from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db.models import F, Q
from django.shortcuts import HttpResponse, redirect, render
from django.utils import timezone
from inventory.models import Brand, CartItem, Category, Order, OrderItem, Product
from payment.models import Payment, PointsTransaction
from payment.services import add_points, points_earned, refund_payment
from review.models import Review
from service.models import Booking, BookingUpdate, Service, TimeSlot
from sitting.models import PetSitter, SittingRequest, SittingUpdate
from user.models import Address, BusinessOwner, Customer, Pet, Staff, User
from user.utils import send_mail_in_background, show_form_errors

from core.models import Outlet

from user.forms import CancelReasonForm, read_cancel_reason

from .forms import (
    OwnerCustomerForm,
    OwnerStaffEditForm,
    OwnerStaffForm,
    PointsAdjustmentForm,
    RejectSitterForm,
)
from .mock_data import (
    DEMO_PASSWORD,
    OWNER_PASSWORD,
    outlets,
    business_owners,
    staff_members,
    customers,
    pet_sitters,
    addresses,
    pets,
    categories,
    brands,
    products,
    cart_items,
    DELIVERY_FEE_CENTS,
    orders,
    services,
    time_slots,
    TIMETABLE_DAYS,
    service_timetable,
    bookings,
    booking_updates,
    owner_coordinates,
    sitting_requests,
    sitting_updates,
    payments,
    SIGN_UP_BONUS,
    points_adjustments,
    reviews,
)


# Pages in this file:
# Load data:         loadData (/loadData/ fills the database with the demo data in mock_data.py)
# Business owner (admin panel)
#   Dashboard:         owner_dashboard
#   Customers:         owner_customers, owner_edit_customer, owner_adjust_points
#   Pet sitters:       owner_sitters, owner_review_sitter
#   Sitting requests:  owner_sitting_requests, owner_cancel_sitting
#   Staff:             owner_staff, owner_add_staff, owner_edit_staff, owner_toggle_staff


# SETTINGS

SGT = ZoneInfo("Asia/Singapore")


# SHARED HELPERS

def today():
    return datetime.now(SGT).date()


def money(cents):
    # 4892000 -> "48,920.00"
    return f"{cents / 100:,.2f}"


# LOAD DATA

def sg_datetime(day_offset, hhmm):
    # A date and time in Singapore, some days from today, e.g. (2, "10:00") = 2 days later at 10am
    day = today() + timedelta(days=day_offset)
    return datetime.combine(day, time.fromisoformat(hhmm), tzinfo=SGT)


def days_ago(n):
    return timezone.now() - timedelta(days=n)


def outlet_time(hhmm):
    # Works when Outlet.opening_time is a time or a date and time
    if Outlet._meta.get_field("opening_time").get_internal_type() == "TimeField":
        return time.fromisoformat(hhmm)
    return sg_datetime(0, hhmm)


def clock_time(value):
    # The outlet's opening or closing time as a plain Singapore time
    # (works when it is saved as a time or a date and time)
    if isinstance(value, datetime):
        return value.astimezone(SGT).time()
    return value


def set_created_at(model, pk, n_days_ago):
    # auto_now_add always saves today, so change the date after saving
    model.objects.filter(pk=pk).update(created_at=days_ago(n_days_ago))


def loadData(request):

    # Clear existing data (children before parents)
    Review.objects.all().delete()
    PointsTransaction.objects.all().delete()
    Payment.objects.all().delete()
    SittingUpdate.objects.all().delete()
    SittingRequest.objects.all().delete()
    BookingUpdate.objects.all().delete()
    Booking.objects.all().delete()
    TimeSlot.objects.all().delete()
    Service.objects.all().delete()
    OrderItem.objects.all().delete()
    Order.objects.all().delete()
    CartItem.objects.all().delete()
    Product.objects.all().delete()
    Brand.objects.all().delete()
    Category.objects.all().delete()
    Address.objects.all().delete()
    Pet.objects.all().delete()
    PetSitter.objects.all().delete()
    User.objects.all().delete()  # also removes Customer, Staff, BusinessOwner and OTP rows
    Outlet.objects.all().delete()

    hashed_password = make_password(DEMO_PASSWORD)

    # Outlets
    for outlet in outlets:
        new_outlet = Outlet(
            name=outlet["name"],
            address=outlet["address"],
            postal_code=outlet["postal_code"],
            phone=outlet["phone"],
            opening_time=outlet_time(outlet["opening_time"]),
            closing_time=outlet_time(outlet["closing_time"]),
            is_active=outlet["is_active"],
        )
        new_outlet.save()

    # Users
    for owner in business_owners:
        new_owner = BusinessOwner(
            username=owner["username"],
            email=owner["email"],
            password=hashed_password,
            first_name=owner["first_name"],
            last_name=owner["last_name"],
            mobile=owner["mobile"],
            is_verified=True,
            is_business_owner=True,
        )
        new_owner.password = make_password(OWNER_PASSWORD)
        new_owner.save()

    for staff in staff_members:
        new_staff = Staff(
            username=staff["username"],
            email=staff["email"],
            password=hashed_password,
            first_name=staff["first_name"],
            last_name=staff["last_name"],
            mobile=staff["mobile"],
            is_verified=True,
            is_staff=True,
            outlet=Outlet.objects.get(name=staff["outlet"]),
        )
        if staff["username"] == "staff_test":
            new_staff.password = make_password(staff["password"])
        new_staff.save()

    for customer in customers:
        new_customer = Customer(
            username=customer["username"],
            email=customer["email"],
            password=hashed_password,
            first_name=customer["first_name"],
            last_name=customer["last_name"],
            mobile=customer["mobile"],
            is_verified=customer["is_verified"],
            point_balance=0,  # set at the end from the points history
        )
        new_customer.save()

    for sitter in pet_sitters:
        reviewer = None
        if sitter["reviewed_by"]:
            reviewer = BusinessOwner.objects.get(username=sitter["reviewed_by"])

        new_sitter = PetSitter(
            username=sitter["username"],
            email=sitter["email"],
            password=hashed_password,
            first_name=sitter["first_name"],
            last_name=sitter["last_name"],
            mobile=sitter["mobile"],
            is_verified=True,
            bio=sitter["bio"],
            postal_code=sitter["postal_code"],
            service_area=sitter["service_area"],
            latitude=sitter["latitude"],
            longitude=sitter["longitude"],
            experience_years=sitter["experience_years"],
            pet_experience=sitter["pet_experience"],
            daily_rate_cents=sitter["daily_rate_cents"],
            application_status=sitter["application_status"],
            rejection_reason=sitter["rejection_reason"],
            reviewed_by=reviewer,
        )
        new_sitter.save()

    # Addresses and pets
    for address in addresses:
        new_address = Address(
            customer=Customer.objects.get(username=address["customer"]),
            label=address["label"],
            is_default=address["is_default"],
            line1=address["line1"],
            line2=address["line2"],
            postal_code=address["postal_code"],
        )
        new_address.save()

    for pet in pets:
        new_pet = Pet(
            owner_id=Customer.objects.get(username=pet["owner"]),
            name=pet["name"],
            profile_picture=pet["photo"],
            pet_type=pet["pet_type"],
            breed=pet["breed"],
            date_of_birth=pet["date_of_birth"],
            weight_kg=pet["weight_kg"],
            allergies=pet["allergies"],
            conditions=pet["conditions"],
            medication=pet["medication"],
            medical_notes=pet["medical_notes"],
            behaviour_notes=pet["behaviour_notes"],
            last_vaccination_date=pet["last_vaccination_date"],
        )
        new_pet.save()

    # Inventory
    for category in categories:
        Category(name=category).save()

    for brand in brands:
        Brand(name=brand).save()

    for product in products:
        new_product = Product(
            name=product["name"],
            category=Category.objects.get(name=product["category"]),
            brand=Brand.objects.get(name=product["brand"]),
            pet_type=product["pet_type"],
            description=product["description"],
            image_url=product["image"] or None,
            price_cents=product["price_cents"],
            stock_quantity=product["stock_quantity"],
            ingredients=product["ingredients"],
            care_tags=product["care_tags"],
            life_stage=product["life_stage"],
        )
        new_product.save()

    for item in cart_items:
        new_item = CartItem(
            customer=Customer.objects.get(username=item["customer"]),
            product=Product.objects.get(name=item["product"]),
            quantity=item["quantity"],
        )
        new_item.save()

    created = (
        {}
    )  # ref ("O1", "B1", "R1") -> saved object, used for payments and reviews

    for order in orders:
        customer = Customer.objects.get(username=order["customer"])

        pickup_outlet = None
        delivery_address = None
        delivery_fee = 0
        est_delivery_date = None

        if order["pickup_outlet"]:
            pickup_outlet = Outlet.objects.get(name=order["pickup_outlet"])
        else:
            delivery_address = Address.objects.get(
                customer=customer, line1=order["delivery_address"]
            )
            delivery_fee = DELIVERY_FEE_CENTS
            if order["est_delivery_in_days"] is not None:
                est_delivery_date = today() + timedelta(
                    days=order["est_delivery_in_days"]
                )

        subtotal = 0
        for product_name, quantity in order["items"]:
            subtotal += Product.objects.get(name=product_name).price_cents * quantity

        new_order = Order(
            customer=customer,
            pickup_outlet=pickup_outlet,
            delivery_address=delivery_address,
            est_delivery_date=est_delivery_date,
            status=order["status"],
            subtotal_cents=subtotal,
            delivery_fee_cents=delivery_fee,
            points_discount_cents=order["points_discount_cents"],
            total_cents=subtotal + delivery_fee - order["points_discount_cents"],
            cancellation_reason=order.get("cancellation_reason", ""),
        )
        if order["status"] == "CANCELLED":
            new_order.cancelled_at = days_ago(order["days_ago"] - 1)
        new_order.save()
        set_created_at(Order, new_order.pk, order["days_ago"])

        for product_name, quantity in order["items"]:
            product = Product.objects.get(name=product_name)
            new_order_item = OrderItem(
                order=new_order,
                product=product,
                quantity=quantity,
                unit_price_cents=product.price_cents,  # price at time of purchase
            )
            new_order_item.save()

        created[order["ref"]] = new_order

    # Services, time slots and bookings
    for service in services:
        new_service = Service(
            name=service["name"],
            category=service["category"],
            description=service["description"],
            duration_minutes=service["duration_minutes"],
            price_cents=service["price_cents"],
            is_active=True,
        )
        new_service.save()

    slots = {}
    for slot in time_slots:
        service = Service.objects.get(name=slot["service"])
        start = sg_datetime(slot["day"], slot["start"])

        if service.duration_minutes:
            end = start + timedelta(minutes=service.duration_minutes)
        else:  # boarding: ends next day at 12:00
            end = sg_datetime(slot["day"] + 1, "12:00")

        new_slot = TimeSlot(
            outlet=Outlet.objects.get(name=slot["outlet"]),
            service=service,
            start_time=start,
            end_time=end,
            capacity=slot["capacity"],
            booked_count=0,  # counted below
        )
        new_slot.save()
        slots[slot["ref"]] = new_slot

    # A month of regular slots from the weekly timetable
    for day in range(TIMETABLE_DAYS):
        weekday = (today() + timedelta(days=day)).weekday()
        for outlet in Outlet.objects.filter(is_active=True):
            opening = clock_time(outlet.opening_time)
            closing = clock_time(outlet.closing_time)
            for row in service_timetable:
                if weekday not in row["days"]:
                    continue
                service = Service.objects.get(name=row["service"])
                for hhmm in row["times"]:
                    if hhmm == "opening":
                        hhmm = opening.strftime("%H:%M")
                    start = sg_datetime(day, hhmm)
                    if service.duration_minutes:
                        end = start + timedelta(minutes=service.duration_minutes)
                        # must finish before the outlet closes
                        if end.time() > closing:
                            continue
                    else:  # boarding: ends next day at 12:00
                        end = sg_datetime(day + 1, "12:00")
                    if start.time() < opening:
                        continue
                    # skip a slot the hand-written list already added
                    if TimeSlot.objects.filter(outlet=outlet, service=service, start_time=start).exists():
                        continue
                    new_slot = TimeSlot(
                        outlet=outlet,
                        service=service,
                        start_time=start,
                        end_time=end,
                        capacity=row["capacity"],
                        booked_count=0,
                    )
                    new_slot.save()

    for booking in bookings:
        customer = Customer.objects.get(username=booking["customer"])
        slot = slots[booking["slot"]]

        price = slot.service.price_cents
        check_out_date = None
        if booking["nights"]:
            price = slot.service.price_cents * booking["nights"]
            check_out_date = slot.start_time.astimezone(SGT).date() + timedelta(
                days=booking["nights"]
            )

        cancelled_at = None
        if booking["status"] == "CANCELLED":
            cancelled_at = days_ago(booking["days_ago"] - 1)

        new_booking = Booking(
            customer=customer,
            pet=Pet.objects.get(owner_id=customer, name=booking["pet"]),
            slot=slot,
            check_out_date=check_out_date,
            status=booking["status"],
            price_cents=price,
            points_discount_cents=booking["points_discount_cents"],
            total_cents=price - booking["points_discount_cents"],
            cancellation_fee_cents=0,
            cancelled_at=cancelled_at,
            cancellation_reason=booking.get("cancellation_reason", ""),
        )
        new_booking.save()
        set_created_at(Booking, new_booking.pk, booking["days_ago"])

        if booking["status"] != "CANCELLED":  # cancelled bookings free up the slot
            slot.booked_count += 1
            slot.save()

        created[booking["ref"]] = new_booking

    for update in booking_updates:
        new_update = BookingUpdate(
            booking=created[update["booking"]],
            staff=Staff.objects.get(username=update["staff"]),
            new_status=update["new_status"],
            note=update["note"],
        )
        new_update.save()

    # Pet sitting
    for request_data in sitting_requests:
        owner = Customer.objects.get(username=request_data["owner"])
        address = Address.objects.filter(customer=owner).first()

        sitter = None
        daily_rate = 5000  # open requests show an estimate until a sitter accepts
        if request_data["sitter"]:
            sitter = PetSitter.objects.get(username=request_data["sitter"])
            daily_rate = sitter.daily_rate_cents

        start_date = today() + timedelta(days=request_data["start_day"])

        new_request = SittingRequest(
            owner=owner,
            sitter=sitter,
            start_date=start_date,
            end_date=start_date + timedelta(days=request_data["days"] - 1),
            location=f"{address.line1} {address.line2}, Singapore {address.postal_code}",
            latitude=owner_coordinates.get(request_data["owner"], (None, None))[0],
            longitude=owner_coordinates.get(request_data["owner"], (None, None))[1],
            care_requirements=request_data["care_requirements"],
            status=request_data["status"],
            total_price_cents=daily_rate * request_data["days"],
            owner_rating=request_data["owner_rating"],
            owner_feedback=request_data["owner_feedback"],
            cancelled_by=request_data.get("cancelled_by", ""),
            cancellation_reason=request_data.get("cancellation_reason", ""),
        )
        new_request.save()
        set_created_at(SittingRequest, new_request.pk, request_data["days_ago"])

        for pet_name in request_data["pets"]:
            new_request.pets.add(Pet.objects.get(owner_id=owner, name=pet_name))

        created[request_data["ref"]] = new_request

    for update in sitting_updates:
        new_update = SittingUpdate(
            request=created[update["request"]],
            sitter=PetSitter.objects.get(username=update["sitter"]),
            new_status=update["new_status"],
            note=update["note"],
        )
        new_update.save()

    # Payments
    payment_for = {}  # ref -> Payment
    for payment in payments:
        target = created[payment["for"]]

        if payment["for"].startswith("B"):
            customer, amount = target.customer, target.total_cents
            new_payment = Payment(
                customer=customer,
                booking=target,
                amount_cents=amount,
                status=payment["status"],
            )
        elif payment["for"].startswith("O"):
            customer, amount = target.customer, target.total_cents
            new_payment = Payment(
                customer=customer,
                order=target,
                amount_cents=amount,
                status=payment["status"],
            )
        else:
            customer, amount = target.owner, target.total_price_cents
            new_payment = Payment(
                customer=customer,
                sitting_request=target,
                amount_cents=amount,
                status=payment["status"],
            )

        new_payment.save()
        set_created_at(Payment, new_payment.pk, payment["days_ago"])
        payment_for[payment["for"]] = new_payment

    # A sitting request only becomes Accepted after the customer pays, so every
    # accepted / in progress / completed request needs a payment. Add any missing one.
    for request_data in sitting_requests:
        job = created[request_data["ref"]]
        paid_statuses = ["accepted", "in_progress", "completed"]
        if job.status in paid_statuses and request_data["ref"] not in payment_for:
            new_payment = Payment(
                customer=job.owner,
                sitting_request=job,
                amount_cents=job.total_price_cents,
                status="COMPLETED",
            )
            new_payment.save()
            set_created_at(Payment, new_payment.pk, max(request_data["days_ago"] - 1, 0))
            payment_for[request_data["ref"]] = new_payment

    # Points history (same wording as the live app, dated on the payment day)
    for customer in Customer.objects.filter(is_verified=True):
        bonus = PointsTransaction(
            customer=customer,
            points=SIGN_UP_BONUS,
            transaction_type="EARNED",
            reason="Sign-up bonus",
        )
        bonus.save()
        set_created_at(PointsTransaction, bonus.pk, 60)

    for ref, payment in payment_for.items():
        target = created[ref]
        payment.refresh_from_db(fields=["created_at"])  # its date was moved back after saving
        if ref.startswith("B"):
            label = f"{target.slot.service.name} booking #{target.pk}"
        elif ref.startswith("O"):
            label = f"order #{target.pk}"
        else:
            label = f"pet sitting #{target.pk}"

        # points used as a discount on this booking/order
        discount = getattr(target, "points_discount_cents", 0)
        if discount:
            redeemed = PointsTransaction(
                customer=payment.customer,
                points=-discount,
                transaction_type="REDEEMED",
                payment=payment,
                reason=f"Redeemed on {label}",
            )
            redeemed.save()
            PointsTransaction.objects.filter(pk=redeemed.pk).update(created_at=payment.created_at)

        # points earned from completed payments (10 points per $1, same function as checkout)
        if payment.status == "COMPLETED" and payment.amount_cents >= 100:
            earned = PointsTransaction(
                customer=payment.customer,
                points=points_earned(payment.amount_cents),
                transaction_type="EARNED",
                payment=payment,
                reason=f"Earned from {label}",
            )
            earned.save()
            PointsTransaction.objects.filter(pk=earned.pk).update(created_at=payment.created_at)

    # points the business owner added or removed by hand, with a reason
    for adjustment in points_adjustments:
        new_adjustment = PointsTransaction(
            customer=Customer.objects.get(username=adjustment["customer"]),
            points=adjustment["points"],
            transaction_type="ADJUSTED",
            reason=adjustment["reason"],
        )
        new_adjustment.save()
        set_created_at(PointsTransaction, new_adjustment.pk, adjustment["days_ago"])

    # point_balance = total of each customer's points history
    for customer in Customer.objects.all():
        total = 0
        for transaction in customer.points_transactions.all():
            total += transaction.points
        customer.point_balance = total
        customer.save()

    # Reviews
    for review in reviews:
        # "B1" = a booking, "R1" = a sitting request
        target = created[review["for"]]
        booking = None
        sitting_request = None
        if review["for"].startswith("B"):
            booking = target
        if review["for"].startswith("R"):
            sitting_request = target
        new_review = Review(
            reviewer=Customer.objects.get(username=review["reviewer"]),
            booking=booking,
            sitting_request=sitting_request,
            rating=review["rating"],
            comment=review["comment"],
        )
        new_review.save()

    summary = (
        f"Data loaded successfully into the database. "
        f"{Outlet.objects.count()} outlets, {User.objects.count()} users, {Pet.objects.count()} pets, "
        f"{Product.objects.count()} products, {Order.objects.count()} orders, "
        f"{Booking.objects.count()} bookings, {SittingRequest.objects.count()} sitting requests, "
        f"{Payment.objects.count()} payments, {Review.objects.count()} reviews. "
        "Demo accounts loaded successfully."
    )
    return HttpResponse(summary)


# BUSINESS OWNER PAGES


# Dashboard

PAID_STATUSES = ["CONFIRMED", "COMPLETED"]  # orders that count as revenue

# bookings that count as revenue: confirmed, pet in care (checked in /
# in progress / ready for pick-up) or completed. Not pending or cancelled.
PAID_BOOKING_STATUSES = [
    Booking.Status.CONFIRMED,
    *Booking.IN_CARE_STATUSES,
    Booking.Status.COMPLETED,
]

# Sort orders for the dashboard tables (used with sort(key=...))
def row_count(row):
    return row["count"]


def pair_count(pair):
    # pair is (name, count), e.g. ("Grooming", 12) -> 12
    name, count = pair
    return count


def percent_change(now, before):
    # e.g. 110 vs 100 -> 10 (%). None when there is nothing to compare with.
    if not before:
        return None
    return round((now - before) * 100 / before)


def paid_sittings(start_date, end_date):
    # Pet sitting jobs the customer paid for between the two dates.
    # Pawpal's 10% cut is counted on the day the customer pays, same as bookings and orders.
    # Refunded payments are not counted.
    payments = (
        Payment.objects.filter(
            status=Payment.Status.COMPLETED,
            sitting_request__isnull=False,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .select_related("sitting_request__owner", "sitting_request__sitter")
        .order_by("-created_at")
    )
    jobs = []
    for payment in payments:
        job = payment.sitting_request
        job.paid_on = payment.created_at.astimezone(SGT).date()
        jobs.append(job)
    return jobs


def revenue_for_period(start_date, end_date, outlet=None):
    # Add up the revenue for one date range, split by type.
    # Delivery orders and pet sitting do not belong to an outlet,
    # so they are left out when one outlet is picked.
    bookings = Booking.objects.filter(
        status__in=PAID_BOOKING_STATUSES,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )
    orders = Order.objects.filter(
        status__in=PAID_STATUSES,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )
    sittings = paid_sittings(start_date, end_date)
    if outlet is not None:
        bookings = bookings.filter(slot__outlet=outlet)
        orders = orders.filter(pickup_outlet=outlet)
        sittings = []  # pet sitting is not linked to an outlet

    services = 0
    for booking in bookings:
        services += booking.total_cents

    products = 0
    delivery = 0
    for order in orders:
        products += order.subtotal_cents - order.points_discount_cents
        delivery += order.delivery_fee_cents

    commission = 0
    sitting_sales = 0
    for sitting in sittings:
        commission += sitting.commission_cents  # Pawpal keeps 10%
        sitting_sales += sitting.total_price_cents

    # booking volume = every booking made in the range that was not cancelled
    booking_count = Booking.objects.filter(
        created_at__date__gte=start_date, created_at__date__lte=end_date
    ).exclude(status="CANCELLED")
    if outlet is not None:
        booking_count = booking_count.filter(slot__outlet=outlet)

    return {
        "services": services,
        "products": products,
        "delivery": delivery,
        "commission": commission,
        "sitting_sales": sitting_sales,
        "total": services + products + delivery + commission,
        "booking_count": booking_count.count(),
    }


def owner_dashboard(request):
    # Filters: date range + outlet
    today_date = today()
    try:
        start = date.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        start = today_date.replace(day=1)  # default: this month so far
    try:
        end = date.fromisoformat(request.GET.get("end", ""))
    except ValueError:
        end = today_date
    if start > end:
        start, end = end, start
        messages.info(request, "Start date was after end date, so they were swapped.")

    outlet = None
    outlet_id = request.GET.get("outlet", "")
    if outlet_id.isdigit():
        outlet = Outlet.objects.filter(pk=outlet_id).first()

    # This period vs the period just before (same length)
    current = revenue_for_period(start, end, outlet)
    number_of_days = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=number_of_days - 1)
    previous = revenue_for_period(previous_start, previous_end, outlet)

    # Revenue breakdown table: one row per type of revenue
    breakdown = []
    streams = [
        ("services", "Service bookings"),
        ("products", "Product sales"),
        ("delivery", "Delivery fees"),
        ("commission", "Pet sitting commission (10%)"),
    ]
    for key, label in streams:
        share = 0
        if current["total"]:
            share = round(current[key] * 100 / current["total"])
        breakdown.append(
            {
                "label": label,
                "amount": money(current[key]),
                "share": share,
                "change": percent_change(current[key], previous[key]),
            }
        )

    # Revenue by outlet
    outlet_rows = []
    for each_outlet in Outlet.objects.filter(is_active=True).order_by("name"):
        outlet_revenue = revenue_for_period(start, end, each_outlet)
        outlet_rows.append(
            {
                "name": each_outlet.name,
                "amount": money(outlet_revenue["total"]),
                "bookings": outlet_revenue["booking_count"],
            }
        )

    # Bookings by service and outlet
    period_bookings = (
        Booking.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
        .exclude(status="CANCELLED")
        .select_related("slot__service", "slot__outlet")
    )
    if outlet is not None:
        period_bookings = period_bookings.filter(slot__outlet=outlet)

    booking_volume = {}  # {(service, outlet): count}
    service_counts = {}  # {service: count}
    for booking in period_bookings:
        key = (booking.slot.service.name, booking.slot.outlet.name)
        booking_volume[key] = booking_volume.get(key, 0) + 1
        service_name = booking.slot.service.name
        service_counts[service_name] = service_counts.get(service_name, 0) + 1

    booking_volume_rows = []
    for (service_name, outlet_name), count in booking_volume.items():
        booking_volume_rows.append(
            {"service": service_name, "outlet": outlet_name, "count": count}
        )
    booking_volume_rows.sort(key=row_count, reverse=True)

    top_services = sorted(service_counts.items(), key=pair_count, reverse=True)[:3]

    # Top-selling products
    period_items = OrderItem.objects.filter(
        order__status__in=PAID_STATUSES,
        order__created_at__date__gte=start,
        order__created_at__date__lte=end,
    ).select_related("product")
    if outlet is not None:
        period_items = period_items.filter(order__pickup_outlet=outlet)

    product_counts = {}  # {product name: quantity sold}
    for item in period_items:
        product_counts[item.product.name] = (
            product_counts.get(item.product.name, 0) + item.quantity
        )
    top_products = sorted(product_counts.items(), key=pair_count, reverse=True)[:3]

    # Points issued and redeemed
    points_issued = 0
    points_redeemed = 0
    for transaction in PointsTransaction.objects.filter(
        created_at__date__gte=start, created_at__date__lte=end
    ):
        if transaction.transaction_type == "EARNED":
            points_issued += transaction.points
        elif transaction.transaction_type == "REDEEMED":
            points_redeemed += -transaction.points  # stored as a negative number

    # Pet sitting commission per job
    sitting_jobs = paid_sittings(start, end)
    paid_to_sitters = 0
    for job in sitting_jobs:
        paid_to_sitters += job.sitter_payout_cents

    # Stacked bar chart: last 6 months
    chart = []
    for months_back in range(5, -1, -1):
        total_months = end.year * 12 + (end.month - 1) - months_back
        month_start = date(total_months // 12, total_months % 12 + 1, 1)
        next_month = date(
            month_start.year + (month_start.month // 12), month_start.month % 12 + 1, 1
        )
        month_end = next_month - timedelta(days=1)
        month_revenue = revenue_for_period(month_start, month_end, outlet)
        chart.append(
            {
                "label": month_start.strftime("%b"),
                "full_label": month_start.strftime("%B %Y"),  # shown in the hover box
                "revenue": month_revenue,
            }
        )

    highest = 1
    for bar in chart:
        highest = max(highest, bar["revenue"]["total"])
    for bar in chart:
        # pixel height of each coloured part of the bar (tallest bar = 180px)
        bar["services_px"] = int(bar["revenue"]["services"] * 180 / highest)
        bar["products_px"] = int(bar["revenue"]["products"] * 180 / highest)
        bar["delivery_px"] = int(bar["revenue"]["delivery"] * 180 / highest)
        bar["commission_px"] = int(bar["revenue"]["commission"] * 180 / highest)
        bar["total"] = money(bar["revenue"]["total"])
        # amounts shown in the hover box
        bar["services"] = money(bar["revenue"]["services"])
        bar["products"] = money(bar["revenue"]["products"])
        bar["delivery"] = money(bar["revenue"]["delivery"])
        bar["commission"] = money(bar["revenue"]["commission"])

    # greeting in Singapore time
    hour = datetime.now(SGT).hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 18:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    context = {
        "active_page": "dashboard",
        "greeting": greeting,
        "start": start,
        "end": end,
        "outlets": Outlet.objects.filter(is_active=True).order_by("name"),
        "selected_outlet": outlet,
        "total_revenue": money(current["total"]),
        "revenue_change": percent_change(current["total"], previous["total"]),
        "booking_count": current["booking_count"],
        "booking_change": current["booking_count"] - previous["booking_count"],
        "commission": money(current["commission"]),
        "sitting_sales": money(current["sitting_sales"]),
        "breakdown": breakdown,
        "outlet_rows": outlet_rows,
        "booking_volume_rows": booking_volume_rows,
        "top_services": top_services,
        "top_products": top_products,
        "points_issued": points_issued,
        "points_redeemed": points_redeemed,
        "sitting_jobs": sitting_jobs,
        "paid_to_sitters": money(paid_to_sitters),
        "chart": chart,
        # Products at or below their low-stock level
        "low_stock_products": Product.objects.filter(
            stock_quantity__lte=F("low_stock_level")
        ).order_by("stock_quantity")[:5],
    }
    return render(request, "core/owner_dashboard.html", context)


# Customers

def owner_customers(request):
    query = request.GET.get("query", "").strip()
    customers = Customer.objects.all()
    if query:
        customers = customers.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(mobile__icontains=query)
        )

    selected_id = request.GET.get("customer", "")
    if not selected_id.isdigit():
        first_customer = customers.first()
        selected_id = None
        if first_customer:
            selected_id = first_customer.pk

    selected_customer = None
    if selected_id:
        selected_customer = (
            Customer.objects.prefetch_related("pets", "addresses").filter(pk=selected_id).first()
        )

    # The selected customer's pets, bookings, orders and points history
    customer_bookings = []
    customer_orders = []
    points_history = []
    if selected_customer is not None:
        customer_bookings = (
            Booking.objects.filter(customer=selected_customer)
            .select_related("pet", "slot__service", "slot__outlet")
            .order_by("-created_at")
        )
        customer_orders = Order.objects.filter(customer=selected_customer).order_by(
            "-created_at"
        )
        points_history = PointsTransaction.objects.filter(
            customer=selected_customer
        ).order_by("-created_at")[:8]

    return render(
        request,
        "core/owner_customers.html",
        {
            "active_page": "customers",
            "customers": customers.order_by("first_name", "last_name"),
            "selected_customer": selected_customer,
            "customer_bookings": customer_bookings,
            "customer_orders": customer_orders,
            "points_history": points_history,
            "query": query,
            "points_form": PointsAdjustmentForm(),
        },
    )


def owner_edit_customer(request, pk):
    try:
        customer = Customer.objects.get(pk=pk)
    except Customer.DoesNotExist:
        messages.error(request, "Customer not found.")
        return redirect("core:owner_customers")

    if request.method == "POST":
        form = OwnerCustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, "Customer profile updated successfully.")
            return redirect(f"/admin-panel/customers/?customer={customer.pk}")
    else:
        form = OwnerCustomerForm(instance=customer)
    return render(
        request,
        "core/owner_customer_form.html",
        {
            "active_page": "customers",
            "form": form,
            "customer": customer,
            "customer_cancel_url": f"/admin-panel/customers/?customer={customer.pk}",
        },
    )


def owner_adjust_points(request, pk):
    # Add or deduct points with a reason; it shows in the points history
    back_to_customer = f"/admin-panel/customers/?customer={pk}"
    if request.method != "POST":
        return redirect(back_to_customer)

    try:
        customer = Customer.objects.get(pk=pk)
    except Customer.DoesNotExist:
        messages.error(request, "Customer not found.")
        return redirect("core:owner_customers")

    form = PointsAdjustmentForm(request.POST, customer=customer)
    if not form.is_valid():
        show_form_errors(request, form)
    else:
        points = form.cleaned_data["points"]
        add_points(customer, points, PointsTransaction.Type.ADJUSTED, form.cleaned_data["reason"])
        messages.success(
            request, f"{points:+d} points saved. New balance: {customer.point_balance}."
        )

    return redirect(back_to_customer)


# Pet sitters (applications)

def owner_sitters(request):
    sitters = PetSitter.objects.order_by("application_status", "first_name")
    return render(
        request,
        "core/owner_sitters_team.html",
        {
            "active_page": "sitters",
            "sitters": sitters,
            "pending_sitters": sitters.filter(
                application_status=PetSitter.Status.PENDING
            ),
            "pending_count": sitters.filter(
                application_status=PetSitter.Status.PENDING
            ).count(),
            # auto_id=False: the same box is shown once per applicant, so it has no id
            "reject_form": RejectSitterForm(auto_id=False),
        },
    )


def owner_review_sitter(request, pk):
    # Approve / Reject buttons send a POST; just opening the URL goes back to the list
    if request.method != "POST":
        return redirect("core:owner_sitters")

    try:
        sitter = PetSitter.objects.get(pk=pk)
    except PetSitter.DoesNotExist:
        messages.error(request, "Pet sitter not found.")
        return redirect("core:owner_sitters")

    action = request.POST.get("action")
    owner = BusinessOwner.objects.get(
        pk=request.session["user_id"]
    )  # the middleware already checked this is the owner
    if action == "approve":
        sitter.application_status = PetSitter.Status.APPROVED
        sitter.rejection_reason = ""
        sitter.reviewed_by = owner
        sitter.save(
            update_fields=[
                "application_status",
                "rejection_reason",
                "reviewed_by",
            ]
        )
        # Tell the applicant by email
        send_mail_in_background(
            "Pawpal: your pet sitter application is approved",
            f"Hi {sitter.first_name}, your application was approved. "
            "Log in to Pawpal to start accepting sitting jobs.",
            None,
            [sitter.email],
            fail_silently=True,
        )
        messages.success(
            request, "Pet sitter application approved. The applicant has been emailed."
        )
    elif action == "reject":
        form = RejectSitterForm(request.POST)
        if not form.is_valid():
            show_form_errors(request, form)
        else:
            reason = form.cleaned_data["rejection_reason"]
            sitter.application_status = PetSitter.Status.REJECTED
            sitter.rejection_reason = reason
            sitter.reviewed_by = owner
            sitter.save(
                update_fields=[
                    "application_status",
                    "rejection_reason",
                    "reviewed_by",
                ]
            )
            send_mail_in_background(
                "Pawpal: update on your pet sitter application",
                f"Hi {sitter.first_name}, your application was not approved.\n"
                f"Reason: {reason}\n"
                "You can update and resubmit it from your application page.",
                None,
                [sitter.email],
                fail_silently=True,
            )
            messages.success(
                request,
                "Pet sitter application rejected. The applicant has been emailed.",
            )
    else:
        messages.error(request, "Invalid sitter review action.")
    return redirect(f"/admin-panel/pet-sitters/?sitter={sitter.pk}")


# Sitting requests

def owner_sitting_requests(request):
    # Every pet sitting request and sitter job, with status tabs, search and a sitter filter
    status = request.GET.get("status", "all")
    query = request.GET.get("query", "").strip()
    sitter_id = request.GET.get("sitter", "")

    jobs = (
        SittingRequest.objects.select_related("owner", "sitter")
        .prefetch_related("pets")
        .order_by("-start_date")
    )
    if sitter_id.isdigit():
        jobs = jobs.filter(sitter_id=sitter_id)
    if query:
        jobs = jobs.filter(
            Q(owner__first_name__icontains=query)
            | Q(owner__last_name__icontains=query)
            | Q(sitter__first_name__icontains=query)
            | Q(sitter__last_name__icontains=query)
        )

    # one tab per status, with how many requests are in it
    tabs = [("all", "All", jobs.count())]
    for value, label in SittingRequest.Status.choices:
        tabs.append((value, label, jobs.filter(status=value).count()))

    if status != "all":
        jobs = jobs.filter(status=status)

    # the request shown in the details panel (first one if none was clicked)
    selected = None
    selected_id = request.GET.get("request", "")
    if selected_id.isdigit():
        selected = SittingRequest.objects.select_related("owner", "sitter").filter(pk=selected_id).first()
    if selected is None:
        selected = jobs.first()

    updates = []
    payment = None
    if selected is not None:
        updates = SittingUpdate.objects.filter(request=selected).select_related("sitter")
        payment = selected.payments.order_by("-created_at").first()

    return render(
        request,
        "core/owner_sitting_requests.html",
        {
            "active_page": "sitting",
            "jobs": jobs,
            "tabs": tabs,
            "status": status,
            "query": query,
            "sitter_id": sitter_id,
            "sitters": PetSitter.objects.filter(application_status=PetSitter.Status.APPROVED).order_by("first_name"),
            "selected": selected,
            "updates": updates,
            "payment": payment,
            "can_cancel": selected is not None and selected.status in ["open", "pending", "accepted"],
            "cancel_form": CancelReasonForm(placeholder="e.g. Sitter is unwell"),
        },
    )


def owner_cancel_sitting(request, pk):
    # The owner cancels a request that has not started yet; a paid request is refunded
    if request.method != "POST":
        return redirect("core:owner_sitting_requests")

    try:
        job = SittingRequest.objects.select_related("owner", "sitter").get(pk=pk)
    except SittingRequest.DoesNotExist:
        messages.error(request, "Sitting request not found.")
        return redirect("core:owner_sitting_requests")

    if job.status not in ["open", "pending", "accepted"]:
        messages.error(request, "Only requests that have not started can be cancelled.")
        return redirect(f"/admin-panel/sitting-requests/?request={job.pk}")

    reason = read_cancel_reason(request)
    if not reason:
        reason = "Cancelled by Pawpal."
    job.status = SittingRequest.Status.CANCELLED
    job.cancelled_by = SittingRequest.CancelledBy.PAWPAL
    job.cancellation_reason = reason
    job.save()
    refund_payment(job, label=f"pet sitting #{job.pk}")  # gives back the money and points if paid

    if job.sitter:
        SittingUpdate(request=job, sitter=job.sitter, new_status=job.status, note=f"Cancelled by Pawpal: {reason}").save()

    # tell the customer and the sitter
    message = f"Pawpal cancelled the pet sitting for {job.start_date:%d %b} to {job.end_date:%d %b}.\nReason: {reason}"
    send_mail_in_background("Pawpal: pet sitting cancelled", message, None, [job.owner.email], fail_silently=True)
    if job.sitter:
        send_mail_in_background("Pawpal: pet sitting cancelled", message, None, [job.sitter.email], fail_silently=True)

    messages.success(request, f"Sitting request #{job.pk} was cancelled.")
    return redirect(f"/admin-panel/sitting-requests/?request={job.pk}")


# Staff

def owner_staff(request):
    return render(
        request,
        "core/owner_staff.html",
        {
            "active_page": "staff",
            "staff_members": Staff.objects.select_related("outlet").order_by(
                "first_name", "last_name"
            ),
        },
    )


def owner_add_staff(request):
    if request.method == "POST":
        form = OwnerStaffForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Staff account created successfully.")
            return redirect("core:owner_staff")
    else:
        form = OwnerStaffForm()
    return render(
        request,
        "core/owner_staff_form.html",
        {
            "active_page": "staff",
            "form": form,
            "page_title": "Add staff account",
            "page_text": "Fill out the details below to create a staff account.",
        },
    )


def owner_edit_staff(request, pk):
    # Edit details and assign the staff member to an outlet
    try:
        staff = Staff.objects.get(pk=pk)
    except Staff.DoesNotExist:
        messages.error(request, "Staff member not found.")
        return redirect("core:owner_staff")

    if request.method == "POST":
        form = OwnerStaffEditForm(request.POST, instance=staff)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"{staff.first_name or staff.username} was updated."
            )
            return redirect("core:owner_staff")
    else:
        form = OwnerStaffEditForm(instance=staff)

    return render(
        request,
        "core/owner_staff_form.html",
        {
            "active_page": "staff",
            "form": form,
            "page_title": f"Edit {staff.first_name} {staff.last_name}",
            "page_text": "Update the details or move this staff member to another outlet.",
        },
    )


def owner_toggle_staff(request, pk):
    if request.method != "POST":
        return redirect("core:owner_staff")
    try:
        staff = Staff.objects.get(pk=pk)
    except Staff.DoesNotExist:
        messages.error(request, "Staff member not found.")
        return redirect("core:owner_staff")

    staff.is_active = not staff.is_active
    staff.save(update_fields=["is_active"])
    if staff.is_active:
        action = "activated"
    else:
        action = "deactivated"
    messages.success(request, f"{staff.first_name or staff.username} was {action}.")
    return redirect("core:owner_staff")
