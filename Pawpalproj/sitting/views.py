import csv
import math
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from user.utils import send_mail_in_background
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render

from payment.forms import PaymentDetailsForm
from payment.services import (
    bind_checkout_form,
    calculate_points_discount,
    checkout_totals,
    get_points_balance,
    record_payment,
)
from review.models import Review
from user.models import OTP, Address, Customer, Pet, User
from user.views import send_otp_code

from .forms import PET_EXPERIENCE_CHOICES, SitterRegistrationForm, SitterReviewForm
from .models import PetSitter, SittingRequest, SittingUpdate
from .onemap import address_to_coordinates, look_up_postal_code

SGT = ZoneInfo("Asia/Singapore")
PAYOUT_DAYS = 3  # payouts are sent 3 days after a job is completed


# Helpers

def today():
    return datetime.now(SGT).date()


def get_sitter(request):
    # The logged-in pet sitter, or None if a sitter is not logged in
    if request.session.get("user_type") != "sitter":
        return None
    try:
        return PetSitter.objects.get(pk=request.session.get("user_id"))
    except PetSitter.DoesNotExist:
        return None


def get_approved_sitter(request):
    # Only APPROVED sitters can see jobs, earnings and profile
    sitter = get_sitter(request)
    if sitter is None or sitter.application_status != PetSitter.Status.APPROVED:
        return None
    return sitter


def distance_km(lat1, lon1, lat2, lon2):
    # Haversine formula: straight-line distance between two map points in km
    lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    a = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(a))


def email_owner(job, subject, message):
    # Tell the pet owner what happened to their sitting request
    send_mail_in_background(subject, message, None, [job.owner.email], fail_silently=True)


def record_update(job, sitter, new_status, note):
    # Save every status change so the owner can see the job's history
    update = SittingUpdate(request=job, sitter=sitter, new_status=new_status, note=note)
    update.save()


def month_before(year, month, count):
    # e.g. month_before(2026, 1, 1) -> (2025, 12)
    total_months = year * 12 + (month - 1) - count
    return total_months // 12, total_months % 12 + 1


# Sign up and Application status

def signup(request):
    # A logged-in sitter uses the same form to edit and resubmit the application
    sitter = get_sitter(request)

    if request.method == "GET":
        form = SitterRegistrationForm(sitter=sitter)
        return render(request, "sitting/signup.html", {"form": form, "edit_mode": sitter is not None})

    elif request.method == "POST":
        form = SitterRegistrationForm(request.POST, request.FILES, sitter=sitter)

        if not form.is_valid():
            return render(request, "sitting/signup.html", {"form": form, "edit_mode": sitter is not None})

        new_sitter = form.save()

        # editing an existing application -> back to the status page
        if sitter is not None:
            messages.success(request, "Application updated and sent for review again.")
            return redirect("sitting:application_status")

        # brand-new sitter -> verify the email address first
        send_otp_code(new_sitter, OTP.Purpose.REGISTER)
        request.session["otp_user_id"] = new_sitter.pk
        request.session["otp_purpose"] = OTP.Purpose.REGISTER
        return redirect("user:verify_otp")


def application_status(request):
    sitter = get_sitter(request)
    if sitter is None:
        return redirect("user:login")

    return render(request, "sitting/application_status.html", {"sitter": sitter})


# Find jobs

def find_jobs(request):
    sitter = get_approved_sitter(request)
    if sitter is None:
        return redirect("sitting:application_status")

    if request.method == "POST":
        action = request.POST.get("action")
        job_id = request.POST.get("request_id")

        try:
            job = SittingRequest.objects.get(pk=job_id, status=SittingRequest.Status.OPEN)
        except (SittingRequest.DoesNotExist, ValueError):
            messages.error(request, "This request is no longer open.")
            return redirect("sitting:sitter_find_jobs")

        # a request sent to ANOTHER sitter cannot be touched by me
        if job.sitter is not None and job.sitter != sitter:
            messages.error(request, "This request was sent to another sitter.")
            return redirect("sitting:sitter_find_jobs")

        if action == "accept":
            # Accepting blocks the job for other sitters.
            # It stays "Pending" until the owner confirms & pays.
            job.sitter = sitter
            job.status = SittingRequest.Status.PENDING
            job.save()
            record_update(job, sitter, SittingRequest.Status.PENDING, f"{sitter.first_name} accepted your request.")
            email_owner(
                job,
                "Pawpal: a sitter accepted your request",
                f"{sitter.first_name} accepted your sitting request for "
                f"{job.start_date:%d %b} to {job.end_date:%d %b}. "
                "Please log in to confirm and pay.",
            )
            messages.success(request, "Job accepted. It is pending until the owner confirms and pays.")
            return redirect("/sitting/my-jobs/?tab=pending")

        elif action == "decline":
            # Only requests sent directly to me can be declined
            if job.sitter != sitter:
                messages.error(request, "Only requests sent to you can be declined.")
                return redirect("sitting:sitter_find_jobs")
            job.status = SittingRequest.Status.DECLINED
            job.save()
            record_update(job, sitter, SittingRequest.Status.DECLINED, f"{sitter.first_name} declined your request.")
            email_owner(
                job,
                "Pawpal: your sitting request was declined",
                f"{sitter.first_name} is not available for {job.start_date:%d %b} to "
                f"{job.end_date:%d %b}. Please choose another sitter.",
            )
            messages.success(request, "Request declined. The owner has been notified.")
            return redirect("sitting:sitter_find_jobs")

        elif action == "hide":
            # "Not interested" on an open request only hides it for me,
            # so we remember the hidden ids in my session
            hidden_ids = request.session.get("hidden_job_ids", [])
            hidden_ids.append(job.pk)
            request.session["hidden_job_ids"] = hidden_ids
            messages.success(request, "Request hidden from your list.")
            return redirect("sitting:sitter_find_jobs")

        messages.error(request, "Unknown action.")
        return redirect("sitting:sitter_find_jobs")

    # GET: read the filters from the query string
    max_distance = request.GET.get("distance", "any")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    pet_types = request.GET.getlist("pet_type")
    job_length = request.GET.get("job_length", "")
    min_pay = request.GET.get("min_pay", "")
    sort = request.GET.get("sort", "nearest")

    # open requests that nobody took + open requests the owner sent to me
    hidden_ids = request.session.get("hidden_job_ids", [])
    jobs = (
        SittingRequest.objects.filter(status=SittingRequest.Status.OPEN)
        .filter(Q(sitter__isnull=True) | Q(sitter=sitter))
        .exclude(pk__in=hidden_ids)
        .select_related("owner")
        .prefetch_related("pets")
    )
    if date_from:
        jobs = jobs.filter(start_date__gte=date_from)
    if date_to:
        jobs = jobs.filter(end_date__lte=date_to)

    # filters that need a calculation are checked one job at a time
    job_list = []
    for job in jobs:
        job.pet_list = list(job.pets.all())
        job.sent_to_me = job.sitter_id == sitter.pk

        # distance from the sitter's service area to the owner's home
        job.distance = None
        if job.latitude and job.longitude and sitter.latitude and sitter.longitude:
            job.distance = round(distance_km(sitter.latitude, sitter.longitude, job.latitude, job.longitude), 1)
        if max_distance != "any":
            if job.distance is None or job.distance > float(max_distance):
                continue

        # job length: drop-in = 1 day, short = 1-3 days, long = 4+ days
        days = job.number_of_days
        if job_length == "dropin" and days != 1:
            continue
        if job_length == "short" and days > 3:
            continue
        if job_length == "long" and days < 4:
            continue

        # minimum pay per day
        if min_pay:
            try:
                if job.total_price_cents / days / 100 < float(min_pay):
                    continue
            except ValueError:
                pass

        # pet type: keep the job if ANY of its pets matches a ticked type
        if pet_types:
            matched = False
            for pet in job.pet_list:
                if pet.pet_type in pet_types:
                    matched = True
            if not matched:
                continue

        job_list.append(job)

    # requests sent to me first, then nearest (or earliest) first
    if sort == "date":
        job_list.sort(key=lambda job: job.start_date)
    else:
        job_list.sort(key=lambda job: job.distance if job.distance is not None else 9999)
    job_list.sort(key=lambda job: not job.sent_to_me)

    # Data for the map pins: only jobs that have a map position.
    # It is sent to the page with |json_script so JavaScript can read it.
    map_pins = []
    for job in job_list:
        if job.latitude and job.longitude:
            map_pins.append({
                "lat": float(job.latitude),
                "lng": float(job.longitude),
                "title": f"{job.owner.first_name} · {job.start_date:%d %b}–{job.end_date:%d %b}",
                "pets": ", ".join(pet.name for pet in job.pet_list),
                "price": job.total_price_display,
                "distance": job.distance,
            })

    map_centre = None
    if sitter.latitude and sitter.longitude:
        map_centre = {"lat": float(sitter.latitude), "lng": float(sitter.longitude)}

    context = {
        "sitter": sitter,
        "jobs": job_list,
        "max_distance": max_distance,
        "date_from": date_from,
        "date_to": date_to,
        "pet_types": pet_types,
        "pet_type_choices": Pet.PetType.choices,
        "job_length": job_length,
        "min_pay": min_pay,
        "sort": sort,
        "distance_choices": ["2", "5", "10", "any"],
        "map_pins": map_pins,
        "map_centre": map_centre,
    }
    return render(request, "sitting/find_jobs.html", context)


# My jobs

def my_jobs(request):
    sitter = get_approved_sitter(request)
    if sitter is None:
        return redirect("sitting:application_status")

    if request.method == "POST":
        action = request.POST.get("action")
        tab = request.POST.get("tab", "all")
        back_to_page = f"/sitting/my-jobs/?tab={tab}"

        try:
            job = SittingRequest.objects.get(pk=request.POST.get("request_id"), sitter=sitter)
        except (SittingRequest.DoesNotExist, ValueError):
            messages.error(request, "Job not found.")
            return redirect(back_to_page)

        if action == "start":
            # Accepted -> In progress (only from the first sitting day)
            if job.status != SittingRequest.Status.ACCEPTED:
                messages.error(request, "Only upcoming jobs can be started.")
            elif job.start_date > today():
                messages.error(request, f"This job starts on {job.start_date:%d %b}.")
            else:
                job.status = SittingRequest.Status.IN_PROGRESS
                job.save()
                record_update(job, sitter, job.status, "Sitting has started.")
                email_owner(job, "Pawpal: your pet sitting has started", f"{sitter.first_name} has started looking after your pet.")
                messages.success(request, "Job started.")

        elif action == "complete":
            # In progress -> Completed
            if job.status != SittingRequest.Status.IN_PROGRESS:
                messages.error(request, "Only jobs in progress can be completed.")
            else:
                job.status = SittingRequest.Status.COMPLETED
                job.save()
                record_update(job, sitter, job.status, "Sitting completed.")
                email_owner(
                    job,
                    "Pawpal: your pet sitting is completed - leave a review",
                    f"{sitter.first_name} has completed the sitting job.\n"
                    f"How did it go? Rate and review {sitter.first_name} here:\n"
                    f"{request.build_absolute_uri('/sitting/requests/')}{job.pk}/#review",
                )
                messages.success(request, "Job marked as completed. Your payout will be sent within 3 days.")

        elif action == "cancel":
            # an upcoming job the owner already paid for
            if job.status != SittingRequest.Status.ACCEPTED:
                messages.error(request, "Only upcoming jobs can be cancelled.")
            else:
                job.status = SittingRequest.Status.CANCELLED
                job.save()
                record_update(job, sitter, job.status, f"{sitter.first_name} cancelled the job.")
                email_owner(job, "Pawpal: your sitter cancelled", f"{sitter.first_name} cancelled your sitting job. Pawpal will refund you.")
                messages.success(request, "Job cancelled. The owner has been notified.")

        elif action == "withdraw":
            # pending (owner has not confirmed) -> give the request back to other sitters
            if job.status != SittingRequest.Status.PENDING:
                messages.error(request, "Only pending jobs can be withdrawn.")
            else:
                record_update(job, sitter, SittingRequest.Status.OPEN, f"{sitter.first_name} withdrew from this request.")
                job.sitter = None
                job.status = SittingRequest.Status.OPEN
                job.save()
                messages.success(request, "You withdrew from this request.")

        elif action == "update":
            # notes and photos while the job is in progress
            note = request.POST.get("note", "").strip()
            photo = request.FILES.get("photo")

            if job.status != SittingRequest.Status.IN_PROGRESS:
                messages.error(request, "Updates can only be posted for jobs in progress.")
            elif not note and not photo:
                messages.error(request, "Add a message or photo before posting an update.")
            elif photo and photo.name.rsplit(".", 1)[-1].lower() not in ["jpg", "jpeg", "png", "webp"]:
                messages.error(request, "Photo must be a JPG, PNG or WEBP file.")
            elif photo and photo.size > 5 * 1024 * 1024:
                messages.error(request, "Photo must be 5 MB or smaller.")
            else:
                update = SittingUpdate(request=job, sitter=sitter, note=note)
                if photo:
                    update.photo = photo
                update.save()
                messages.success(request, "Update posted. The owner can see it in their booking timeline.")

        elif action == "rate":
            # rate the owner 1-5 stars after the job is completed
            rating = request.POST.get("owner_rating", "")
            if job.status != SittingRequest.Status.COMPLETED:
                messages.error(request, "You can only rate the owner after the job is completed.")
            elif job.owner_rating:
                messages.error(request, "You have already rated this owner.")
            elif rating not in ["1", "2", "3", "4", "5"]:
                messages.error(request, "Choose a rating from 1 to 5 stars.")
            else:
                job.owner_rating = int(rating)
                job.owner_feedback = request.POST.get("owner_feedback", "").strip()
                job.save()
                messages.success(request, "Thanks! Your rating was saved.")

        else:
            messages.error(request, "Unknown action.")

        return redirect(back_to_page)

    # GET: sort my jobs into groups
    tab = request.GET.get("tab", "all")
    jobs = (
        SittingRequest.objects.filter(sitter=sitter)
        .select_related("owner")
        .prefetch_related("pets", "updates")
        .order_by("start_date")
    )

    in_progress = []
    upcoming = []
    pending = []
    completed = []
    cancelled = []

    for job in jobs:
        job.pet_list = list(job.pets.all())
        job.latest_update = job.updates.first()  # updates are newest first

        if job.status == SittingRequest.Status.IN_PROGRESS:
            # "Day 2 of 4" progress bar
            day_number = (today() - job.start_date).days + 1
            day_number = max(1, min(day_number, job.number_of_days))
            job.day_number = day_number
            job.progress_percent = int(day_number * 100 / job.number_of_days)
            in_progress.append(job)
        elif job.status == SittingRequest.Status.ACCEPTED:
            job.starts_in = (job.start_date - today()).days
            job.can_start = job.start_date <= today()
            upcoming.append(job)
        elif job.status == SittingRequest.Status.PENDING:
            pending.append(job)
        elif job.status == SittingRequest.Status.COMPLETED:
            completed.append(job)
        else:  # cancelled or declined
            cancelled.append(job)

    completed.reverse()  # latest completed job first

    counts = {
        "all": len(jobs),
        "in_progress": len(in_progress),
        "upcoming": len(upcoming),
        "pending": len(pending),
        "completed": len(completed),
        "cancelled": len(cancelled),
    }

    # right column: post an update + timeline for the first job in progress
    timeline = []
    if in_progress:
        timeline = SittingUpdate.objects.filter(request=in_progress[0])[:5]

    next_job = upcoming[0] if upcoming else None

    context = {
        "sitter": sitter,
        "tab": tab,
        "tabs": [
            ("all", "All"),
            ("in_progress", "In progress"),
            ("upcoming", "Upcoming"),
            ("pending", "Pending"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        "counts": counts,
        "in_progress": in_progress,
        "upcoming": upcoming,
        "pending": pending,
        "completed": completed,
        "cancelled": cancelled,
        "timeline": timeline,
        "next_job": next_job,
    }
    return render(request, "sitting/my_jobs.html", context)


# Earnings

def earnings(request):
    sitter = get_approved_sitter(request)
    if sitter is None:
        return redirect("sitting:application_status")

    # which month to show, e.g. ?month=2026-11 (default: this month)
    try:
        year, month = request.GET.get("month", "").split("-")
        year, month = int(year), int(month)
    except ValueError:
        year, month = today().year, today().month

    completed_jobs = (
        SittingRequest.objects.filter(sitter=sitter, status=SittingRequest.Status.COMPLETED)
        .select_related("owner")
        .prefetch_related("pets")
        .order_by("-end_date")
    )

    # go through every completed job once and add up the totals
    month_jobs = []
    month_price = 0
    month_commission = 0
    month_payout = 0
    pending_payout = 0
    pending_count = 0
    lifetime_payout = 0

    for job in completed_jobs:
        # paid once PAYOUT_DAYS have passed since the last sitting day
        job.is_paid = (today() - job.end_date).days > PAYOUT_DAYS
        job.pet_list = list(job.pets.all())

        lifetime_payout += job.sitter_payout_cents
        if not job.is_paid:
            pending_payout += job.sitter_payout_cents
            pending_count += 1

        if job.end_date.year == year and job.end_date.month == month:
            month_jobs.append(job)
            month_price += job.total_price_cents
            month_commission += job.commission_cents
            month_payout += job.sitter_payout_cents

    # "Download statement" -> the selected month as a CSV file
    if request.GET.get("download") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="pawpal-earnings-{year}-{month:02d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Start", "End", "Owner", "Pets", "Job price", "Commission", "Payout", "Status"])
        for job in month_jobs:
            writer.writerow([
                job.start_date, job.end_date, job.owner.first_name,
                ", ".join(pet.name for pet in job.pet_list),
                job.total_price_display, job.commission_display, job.sitter_payout_display,
                "Paid" if job.is_paid else "Pending",
            ])
        return response

    # bar chart: payouts for the last 6 months
    chart = []
    for count in range(5, -1, -1):
        chart_year, chart_month = month_before(year, month, count)
        total = 0
        for job in completed_jobs:
            if job.end_date.year == chart_year and job.end_date.month == chart_month:
                total += job.sitter_payout_cents
        chart.append({"label": datetime(chart_year, chart_month, 1).strftime("%b"), "cents": total})

    highest = max(bar["cents"] for bar in chart) or 1
    for bar in chart:
        bar["amount"] = f"{bar['cents'] / 100:.0f}"
        bar["height"] = int(bar["cents"] * 160 / highest) + 4  # pixels, +4 so 0 still shows

    # reviews that pet owners wrote about my sitting jobs
    reviews = Review.objects.filter(sitting_request__sitter=sitter).select_related("reviewer")
    rating_total = 0
    for review in reviews:
        rating_total += review.rating
    average_rating = round(rating_total / len(reviews), 1) if reviews else None

    # example breakdown card uses the latest job of the month
    example_job = month_jobs[0] if month_jobs else None

    context = {
        "sitter": sitter,
        "month_value": f"{year}-{month:02d}",
        "month_label": datetime(year, month, 1).strftime("%b %Y"),
        "month_jobs": month_jobs,
        "month_price": f"{month_price / 100:.2f}",
        "month_commission": f"{month_commission / 100:.2f}",
        "month_payout": f"{month_payout / 100:.2f}",
        "pending_payout": f"{pending_payout / 100:.2f}",
        "pending_count": pending_count,
        "lifetime_payout": f"{lifetime_payout / 100:.2f}",
        "lifetime_count": len(completed_jobs),
        "average_rating": average_rating,
        "review_count": len(reviews),
        "recent_reviews": reviews[:3],
        "chart": chart,
        "example_job": example_job,
    }
    return render(request, "sitting/earnings.html", context)


# Profile (sitter profile, rate, ID document, account, password)

def profile(request):
    sitter = get_approved_sitter(request)
    if sitter is None:
        return redirect("sitting:application_status")

    if request.method == "POST":
        form_name = request.POST.get("form")

        if form_name == "profile":
            # Sitter profile: what pet owners see
            errors = []
            # Only the postal code is typed; the map position and area name come from OneMap
            postal_code = request.POST.get("postal_code", "").strip()
            place = None
            if not (postal_code.isdigit() and len(postal_code) == 6):
                errors.append("Enter a 6-digit Singapore postal code.")
            elif postal_code != sitter.postal_code or sitter.latitude is None:
                place = look_up_postal_code(postal_code)
                if place == {}:
                    errors.append("We couldn't find this postal code. Please check it.")
                elif place is None:
                    # OneMap didn't answer: keep the old postal code so it never
                    # points to a different place than the saved map position
                    errors.append("We couldn't check your postal code right now. Please try again.")

            try:
                experience_years = int(request.POST.get("experience_years", ""))
                if experience_years < 0:
                    raise ValueError
            except ValueError:
                errors.append("Years of experience must be 0 or more.")

            try:
                daily_rate = Decimal(request.POST.get("daily_rate", ""))
                if daily_rate <= 0:
                    raise InvalidOperation
            except InvalidOperation:
                errors.append("Daily rate must be more than 0.")

            id_document = request.FILES.get("id_document")
            if id_document:
                if id_document.name.rsplit(".", 1)[-1].lower() not in ["jpg", "jpeg", "png", "pdf"]:
                    errors.append("ID document must be a PDF, JPG or PNG file.")
                elif id_document.size > 5 * 1024 * 1024:
                    errors.append("ID document must be 5 MB or smaller.")

            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                sitter.bio = request.POST.get("bio", "").strip()
                sitter.postal_code = postal_code
                if place:
                    sitter.latitude = place["latitude"]
                    sitter.longitude = place["longitude"]
                    sitter.service_area = place["area"]
                sitter.experience_years = experience_years
                sitter.daily_rate_cents = int(daily_rate * 100)
                sitter.pet_experience = ", ".join(request.POST.getlist("pet_experience"))
                if id_document:
                    sitter.id_document = id_document
                sitter.save()
                messages.success(request, "Sitter profile saved.")

        elif form_name == "account":
            # Account details
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            email = request.POST.get("email", "").strip().lower()
            mobile = request.POST.get("mobile", "").strip()

            if not first_name or not email:
                messages.error(request, "First name and email are required.")
            elif User.objects.filter(email__iexact=email).exclude(pk=sitter.pk).exists():
                messages.error(request, "Another account already uses this email.")
            elif not (mobile.isdigit() and len(mobile) == 8):
                messages.error(request, "Mobile number must be 8 digits.")
            else:
                sitter.first_name = first_name
                sitter.last_name = last_name
                sitter.email = email
                sitter.mobile = mobile
                sitter.save()
                request.session["username"] = sitter.first_name
                messages.success(request, "Account details updated.")

        elif form_name == "password":
            # Change password: current one must be correct first
            current = request.POST.get("current_password", "")
            new = request.POST.get("new_password", "")
            confirm = request.POST.get("confirm_password", "")

            if not check_password(current, sitter.password):
                messages.error(request, "Your current password is incorrect.")
            elif len(new) < 8:
                messages.error(request, "New password must be at least 8 characters.")
            elif new != confirm:
                messages.error(request, "New passwords do not match.")
            else:
                sitter.password = make_password(new)
                sitter.save()
                messages.success(request, "Password changed.")

        else:
            messages.error(request, "Unknown form.")

        return redirect("sitting:sitter_profile")

    # GET
    # tick the chips the sitter already has (saved as "Dogs, Cats")
    my_experience = [item.strip().lower() for item in sitter.pet_experience.split(",")]
    experience_chips = []
    for value, label in PET_EXPERIENCE_CHOICES:
        experience_chips.append({"value": value, "label": label, "checked": value.lower() in my_experience})

    reviews = Review.objects.filter(sitting_request__sitter=sitter)
    rating_total = 0
    for review in reviews:
        rating_total += review.rating
    average_rating = round(rating_total / len(reviews), 1) if reviews else None

    jobs_done = SittingRequest.objects.filter(sitter=sitter, status=SittingRequest.Status.COMPLETED).count()

    context = {
        "sitter": sitter,
        "experience_chips": experience_chips,
        "average_rating": average_rating,
        "jobs_done": jobs_done,
        # what the sitter receives per day after Pawpal's 10% commission
        "daily_payout": f"{sitter.daily_rate_cents * 0.9 / 100:.2f}",
    }
    return render(request, "sitting/profile.html", context)


# Customer side · Find a Pet Sitter

# words to look for in a sitter's "pet experience" for each pet type
PET_TYPE_WORDS = {"DOG": "dog", "CAT": "cat", "OTHER": "small"}

# statuses where the sitter is already booked for those days
BUSY_STATUSES = [
    SittingRequest.Status.PENDING,
    SittingRequest.Status.ACCEPTED,
    SittingRequest.Status.IN_PROGRESS,
]


def get_customer(request):
    # The logged-in customer, or None
    if request.session.get("user_type") != "customer":
        return None
    try:
        return Customer.objects.get(pk=request.session.get("user_id"))
    except Customer.DoesNotExist:
        return None


def sitter_rating(sitter):
    # average stars and number of reviews owners left for this sitter
    reviews = Review.objects.filter(sitting_request__sitter=sitter)
    total = 0
    for review in reviews:
        total += review.rating
    if not reviews:
        return None, 0
    return round(total / len(reviews), 1), len(reviews)


def read_request_form(customer, data):
    """Read and check the "Your request" form.

    Returns (form_values, errors). form_values keeps what was typed so the
    form can be shown again; it also holds the real objects once valid.
    """
    values = {
        "start": data.get("start", ""),
        "end": data.get("end", ""),
        "address_id": data.get("address", ""),
        "pet_ids": data.getlist("pets"),
        "care": data.get("care", "").strip(),
    }
    errors = []

    try:
        start = date.fromisoformat(values["start"])
        end = date.fromisoformat(values["end"])
        if start < today():
            errors.append("The start date cannot be in the past.")
        elif end < start:
            errors.append("The end date must be on or after the start date.")
        values["start_date"] = start
        values["end_date"] = end
        values["days"] = (end - start).days + 1
    except ValueError:
        errors.append("Choose the sitting dates.")

    try:
        values["address"] = Address.objects.get(pk=values["address_id"], customer=customer)
    except (Address.DoesNotExist, ValueError):
        errors.append("Choose the location (one of your saved addresses).")

    # only the customer's own pets can be chosen
    values["pets"] = list(Pet.objects.filter(owner_id=customer, pk__in=[pk for pk in values["pet_ids"] if pk.isdigit()]))
    if not values["pets"]:
        errors.append("Choose at least one pet that needs care.")

    return values, errors


def recommend_sitters(values, latitude, longitude):
    """Rank approved, available sitters for this request.

    score = rating x 2  +  2 per pet type they have experience with
            + 1.5 per completed job with the same breed  -  distance (km) / 2
    """
    breeds = [pet.breed for pet in values["pets"] if pet.breed]
    results = []

    for sitter in PetSitter.objects.filter(application_status=PetSitter.Status.APPROVED, is_active=True):
        # availability: skip sitters already booked on any of these days
        busy = SittingRequest.objects.filter(
            sitter=sitter,
            status__in=BUSY_STATUSES,
            start_date__lte=values["end_date"],
            end_date__gte=values["start_date"],
        ).exists()
        if busy:
            continue

        sitter.distance = None
        if latitude and sitter.latitude and sitter.longitude:
            sitter.distance = round(distance_km(latitude, longitude, sitter.latitude, sitter.longitude), 1)

        sitter.rating, sitter.review_count = sitter_rating(sitter)

        experience = sitter.pet_experience.lower()
        type_matches = 0
        for pet in values["pets"]:
            if PET_TYPE_WORDS.get(pet.pet_type, "") in experience:
                type_matches += 1

        sitter.breed_jobs = 0
        if breeds:
            sitter.breed_jobs = (
                SittingRequest.objects.filter(sitter=sitter, status=SittingRequest.Status.COMPLETED, pets__breed__in=breeds)
                .distinct()
                .count()
            )

        sitter.score = (sitter.rating or 0) * 2 + type_matches * 2 + sitter.breed_jobs * 1.5
        sitter.score -= sitter.distance / 2 if sitter.distance is not None else 5

        sitter.price = f"{sitter.daily_rate_cents * values['days'] / 100:.2f}"
        results.append(sitter)

    results.sort(key=lambda sitter: sitter.score, reverse=True)
    return results


def find_sitter(request):
    customer = get_customer(request)
    if customer is None:
        return redirect("user:login")

    addresses = Address.objects.filter(customer=customer).order_by("-is_default", "label")
    pets = Pet.objects.filter(owner_id=customer).order_by("name")

    # POST: send the request to one sitter, or to all sitters
    if request.method == "POST":
        values, errors = read_request_form(customer, request.POST)
        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect("sitting:find_sitter")

        latitude, longitude = address_to_coordinates(values["address"])
        address = values["address"]

        new_request = SittingRequest(
            owner=customer,
            start_date=values["start_date"],
            end_date=values["end_date"],
            location=f"{address.line1} {address.line2}, Singapore {address.postal_code}".replace("  ", " "),
            latitude=latitude,
            longitude=longitude,
            care_requirements=values["care"],
            status=SittingRequest.Status.OPEN,
        )

        if request.POST.get("action") == "send":
            # send to the sitter the owner picked
            try:
                sitter = PetSitter.objects.get(
                    pk=request.POST.get("sitter_id"), application_status=PetSitter.Status.APPROVED
                )
            except (PetSitter.DoesNotExist, ValueError):
                messages.error(request, "That sitter is not available.")
                return redirect("sitting:find_sitter")
            new_request.sitter = sitter
            new_request.total_price_cents = sitter.daily_rate_cents * values["days"]
        else:
            # open request: every nearby sitter can see it in Find Jobs.
            # Price estimate = average daily rate of approved sitters.
            rates = [s.daily_rate_cents for s in PetSitter.objects.filter(application_status=PetSitter.Status.APPROVED)]
            average_rate = sum(rates) // len(rates) if rates else 5000
            new_request.total_price_cents = average_rate * values["days"]

        new_request.save()
        for pet in values["pets"]:
            new_request.pets.add(pet)

        if new_request.sitter:
            send_mail_in_background(
                "Pawpal: you have a new sitting request",
                f"{customer.first_name} sent you a sitting request for {new_request.start_date:%d %b} "
                f"to {new_request.end_date:%d %b}. Log in to accept or decline it.",
                None,
                [new_request.sitter.email],
                fail_silently=True,
            )
            messages.success(request, f"Request sent to {new_request.sitter.first_name}. We'll email you when they reply.")
        else:
            messages.success(request, "Request posted. Nearby sitters can now accept it.")
        return redirect("sitting:request_detail", pk=new_request.pk)

    # GET: show the form, and recommendations once it is filled
    sitters = None
    values = {"pet_ids": [], "address_id": ""}
    estimate = None
    if request.GET.get("start"):
        values, errors = read_request_form(customer, request.GET)
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            latitude, longitude = address_to_coordinates(values["address"])
            sitters = recommend_sitters(values, latitude, longitude)

            # Estimated price range before sending
            rates = [s.daily_rate_cents for s in PetSitter.objects.filter(application_status=PetSitter.Status.APPROVED)]
            if rates:
                estimate = {
                    "days": values["days"],
                    "low": f"{min(rates) * values['days'] / 100:.0f}",
                    "high": f"{max(rates) * values['days'] / 100:.0f}",
                }

    # pre-select the default address the first time
    if not values.get("address_id"):
        default_address = addresses.first()
        values["address_id"] = str(default_address.pk) if default_address else ""

    my_requests = (
        SittingRequest.objects.filter(owner=customer).select_related("sitter").order_by("-created_at")[:3]
    )

    context = {
        "addresses": addresses,
        "pets": pets,
        "values": values,
        "sitters": sitters,
        "estimate": estimate,
        "my_requests": my_requests,
        "today_iso": today().isoformat(),  # earliest date the calendar allows
        "query_string": request.GET.urlencode(),  # keeps the form when going to a profile and back
    }
    return render(request, "sitting/find_sitter.html", context)


def sitter_public_profile(request, pk):
    # What a pet owner sees before sending a request
    customer = get_customer(request)
    if customer is None:
        return redirect("user:login")

    try:
        sitter = PetSitter.objects.get(pk=pk, application_status=PetSitter.Status.APPROVED)
    except PetSitter.DoesNotExist:
        messages.error(request, "Sitter not found.")
        return redirect("sitting:find_sitter")

    rating, review_count = sitter_rating(sitter)
    reviews = Review.objects.filter(sitting_request__sitter=sitter).select_related("reviewer")[:10]
    jobs_done = SittingRequest.objects.filter(sitter=sitter, status=SittingRequest.Status.COMPLETED).count()

    context = {
        "sitter": sitter,
        "rating": rating,
        "review_count": review_count,
        "reviews": reviews,
        "jobs_done": jobs_done,
        "query_string": request.GET.urlencode(),
    }
    return render(request, "sitting/sitter_public_profile.html", context)


def my_sitting_requests(request):
    # "View all" list of the customer's sitting requests
    customer = get_customer(request)
    if customer is None:
        return redirect("user:login")

    requests_list = (
        SittingRequest.objects.filter(owner=customer)
        .select_related("sitter")
        .prefetch_related("pets")
        .order_by("-created_at")
    )
    return render(request, "sitting/my_sitting_requests.html", {"requests_list": requests_list})


def request_detail(request, pk):
    # Track status, see the sitter's notes & photos, cancel, review
    customer = get_customer(request)
    if customer is None:
        return redirect("user:login")

    try:
        job = SittingRequest.objects.select_related("sitter").get(pk=pk, owner=customer)
    except SittingRequest.DoesNotExist:
        messages.error(request, "Sitting request not found.")
        return redirect("sitting:my_sitting_requests")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "cancel":
            # only before the owner has paid
            if job.status not in [SittingRequest.Status.OPEN, SittingRequest.Status.PENDING]:
                messages.error(request, "This request can no longer be cancelled here. Please contact Pawpal.")
            else:
                job.status = SittingRequest.Status.CANCELLED
                job.save()
                if job.sitter:
                    send_mail_in_background(
                        "Pawpal: a sitting request was cancelled",
                        f"{customer.first_name} cancelled the request for {job.start_date:%d %b} to {job.end_date:%d %b}.",
                        None,
                        [job.sitter.email],
                        fail_silently=True,
                    )
                messages.success(request, "Request cancelled.")

        elif action == "review":
            # Add a review, or update my review if I already wrote one
            if job.status != SittingRequest.Status.COMPLETED:
                messages.error(request, "You can review the sitter after the job is completed.")
                return redirect("sitting:request_detail", pk=job.pk)

            my_review = Review.objects.filter(sitting_request=job, reviewer=customer).first()
            form = SitterReviewForm(request.POST, request.FILES, instance=my_review)

            if form.is_valid():
                review = form.save(commit=False)
                review.reviewer = customer
                review.sitting_request = job
                review.save()
                if my_review is None:
                    messages.success(request, "Thanks for your review!")
                else:
                    messages.success(request, "Your review was updated.")
            else:
                # show the form again with the error messages under each field
                return render_request_detail(request, job, customer, review_form=form, editing=True)

        elif action == "delete_review":
            my_review = Review.objects.filter(sitting_request=job, reviewer=customer).first()
            if my_review is None:
                messages.error(request, "There is no review to delete.")
            else:
                my_review.delete()
                messages.success(request, "Your review was deleted.")

        else:
            messages.error(request, "Unknown action.")

        return redirect("sitting:request_detail", pk=job.pk)

    # ?edit=1 opens the form again to change an existing review
    return render_request_detail(request, job, customer, editing=request.GET.get("edit") == "1")


def render_request_detail(request, job, customer, review_form=None, editing=False):
    # Builds the request page. Used for normal visits, and to show a review
    # form again with its errors after a failed submit.
    my_review = Review.objects.filter(sitting_request=job, reviewer=customer).first()
    if review_form is None:
        review_form = SitterReviewForm(instance=my_review)

    # status steps for the progress line
    steps = [
        ("open", "Sent"),
        ("pending", "Sitter accepted"),
        ("accepted", "Confirmed & paid"),
        ("in_progress", "In progress"),
        ("completed", "Completed"),
    ]
    step_order = [value for value, label in steps]
    current_index = step_order.index(job.status) if job.status in step_order else -1

    payment = job.payments.order_by("-created_at").first()
    context = {
        "job": job,
        "pets": job.pets.all(),
        "updates": SittingUpdate.objects.filter(request=job),
        "steps": steps,
        "current_index": current_index,
        "my_review": my_review,
        "review_form": review_form,
        # show the form when there is no review yet, or when editing it
        "show_review_form": job.status == SittingRequest.Status.COMPLETED and (my_review is None or editing),
        "payment": payment,
        "paid_amount": f"{payment.amount_cents / 100:.2f}" if payment else None,
    }
    return render(request, "sitting/request_detail.html", context)


def pay_for_request(request, pk):
    # The sitter accepted (status "pending") -> owner confirms & pays
    customer = get_customer(request)
    if customer is None:
        return redirect("user:login")

    try:
        job = SittingRequest.objects.select_related("sitter").get(pk=pk, owner=customer)
    except SittingRequest.DoesNotExist:
        messages.error(request, "Sitting request not found.")
        return redirect("sitting:my_sitting_requests")

    if job.status != SittingRequest.Status.PENDING:
        messages.error(request, "This request is not waiting for payment.")
        return redirect("sitting:request_detail", pk=job.pk)

    # the same card + points form as the shop and service checkouts
    points_balance = get_points_balance(customer)
    form, preview_points = bind_checkout_form(request, PaymentDetailsForm, customer, points_balance)

    if request.POST.get("action") == "place_order" and form.is_valid():
        discount_cents = calculate_points_discount(
            job.total_price_cents,
            form.cleaned_data.get("points_to_redeem") or 0,
            points_balance,
        )
        record_payment(
            customer,
            form,
            amount_cents=job.total_price_cents - discount_cents,
            points_redeemed=discount_cents,
            label=f"Pet sitting #{job.pk}",
            sitting_request=job,
        )
        job.status = SittingRequest.Status.ACCEPTED
        job.save()
        record_update(job, job.sitter, job.status, f"{customer.first_name} confirmed and paid.")
        send_mail_in_background(
            "Pawpal: sitting job confirmed",
            f"{customer.first_name} confirmed and paid for {job.start_date:%d %b} to {job.end_date:%d %b}. "
            "It is now in your Upcoming jobs.",
            None,
            [job.sitter.email],
            fail_silently=True,
        )
        messages.success(request, f"Paid! {job.sitter.first_name} is confirmed for your pet sitting.")
        return redirect("sitting:request_detail", pk=job.pk)

    discount_cents = calculate_points_discount(job.total_price_cents, preview_points, points_balance)
    context = {
        "form": form,
        "job": job,
        "pets": job.pets.all(),
        "summary_title": "Pet sitting summary",
        "checkout_intro": "Use your points and pay by card to confirm your pet sitter",
        "submit_text": "Confirm & pay",
        "back_url": f"/sitting/requests/{job.pk}/",
        "back_text": "Back to request",
        **checkout_totals(job.total_price_cents, discount_cents),
    }
    return render(request, "sitting/pay_request.html", context)
