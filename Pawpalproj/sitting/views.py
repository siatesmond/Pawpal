import csv
import math
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render

from review.models import Review
from user.models import OTP, Pet, User
from user.views import send_otp_code

from .forms import PET_EXPERIENCE_CHOICES, SitterRegistrationForm
from .models import PetSitter, SittingRequest, SittingUpdate

SGT = ZoneInfo("Asia/Singapore")
PAYOUT_DAYS = 3  # payouts are sent 3 days after a job is completed (Figma S5)


# =====================================================================
# Helpers
# =====================================================================


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
    # Only APPROVED sitters can see jobs, earnings and profile (US-047)
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
    # Tell the pet owner what happened to their sitting request (US-044, US-049)
    send_mail(subject, message, None, [job.owner.email], fail_silently=True)


def record_update(job, sitter, new_status, note):
    # Save every status change so the owner can see the job's history (US-050)
    update = SittingUpdate(request=job, sitter=sitter, new_status=new_status, note=note)
    update.save()


def month_before(year, month, count):
    # e.g. month_before(2026, 1, 1) -> (2025, 12)
    total_months = year * 12 + (month - 1) - count
    return total_months // 12, total_months % 12 + 1


# =====================================================================
# S1a · Sign up (US-045) and S1b · Application status (US-046)
# =====================================================================


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


# =====================================================================
# S3 · Find jobs (US-048, US-049)
# =====================================================================


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
            # Accepting blocks the job for other sitters (US-049).
            # It stays "Pending" until the owner confirms & pays (Figma S3 / S4).
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
            # Only requests sent directly to me can be declined (US-049)
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

    # ---------- GET: read the filters from the query string ----------
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


# =====================================================================
# S4 · My jobs (US-050, US-052)
# =====================================================================


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
                email_owner(job, "Pawpal: your pet sitting is completed", f"{sitter.first_name} has completed the sitting job.")
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
            # notes and photos while the job is in progress (US-050)
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
            # rate the owner 1-5 stars after the job is completed (US-052)
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

    # ---------- GET: sort my jobs into groups ----------
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


# =====================================================================
# S5 · Earnings (US-051)
# =====================================================================


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


# =====================================================================
# S6 · Profile (sitter profile, rate, ID document, account, password)
# =====================================================================


def profile(request):
    sitter = get_approved_sitter(request)
    if sitter is None:
        return redirect("sitting:application_status")

    if request.method == "POST":
        form_name = request.POST.get("form")

        if form_name == "profile":
            # ---- Sitter profile: what pet owners see ----
            errors = []
            service_area = request.POST.get("service_area", "").strip()
            if not service_area:
                errors.append("Service area is required.")

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
                sitter.service_area = service_area
                sitter.experience_years = experience_years
                sitter.daily_rate_cents = int(daily_rate * 100)
                sitter.pet_experience = ", ".join(request.POST.getlist("pet_experience"))
                if id_document:
                    sitter.id_document = id_document
                sitter.save()
                messages.success(request, "Sitter profile saved.")

        elif form_name == "account":
            # ---- Account details ----
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
            # ---- Change password: current one must be correct first ----
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

    # ---------- GET ----------
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
