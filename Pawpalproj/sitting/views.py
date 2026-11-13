import math
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import dateformat, timezone
from payment.forms import PaymentDetailsForm
from payment.services import (
    bind_checkout_form,
    calculate_points_discount,
    checkout_totals,
    get_points_balance,
    record_payment,
    refund_payment,
)
from review.models import Review
from user.forms import CancelReasonForm, PasswordChangeForm, read_cancel_reason
from user.models import OTP, Address, Pet
from user.utils import get_current_customer, send_mail_in_background, show_form_errors
from user.views import send_otp_code

from .forms import (
    OwnerRatingForm,
    SitterAccountForm,
    SitterProfileForm,
    SitterRegistrationForm,
    SitterReviewForm,
    SittingUpdateForm,
)
from .models import PetSitter, SittingRequest, SittingUpdate
from .onemap import address_to_coordinates

# Pages in this file:
# Pet sitter side
#   Sign up:        signup, application_status
#   Find jobs:      find_jobs
#   My jobs:        my_jobs
#   Earnings:       earnings
#   Profile:        profile
# Pet owner (customer) side
#   Find a sitter:  find_sitter, sitter_public_profile
#   My requests:    my_sitting_requests, request_detail, cancel_request, pay_for_request


# SETTINGS

SGT = ZoneInfo("Asia/Singapore")

# words to look for in a sitter's "pet experience" for each pet type
PET_TYPE_WORDS = {"DOG": "dog", "CAT": "cat", "OTHER": "small"}

# statuses where the sitter is already booked for those days
BUSY_STATUSES = [
    SittingRequest.Status.PENDING,
    SittingRequest.Status.ACCEPTED,
    SittingRequest.Status.IN_PROGRESS,
]


# SHARED HELPERS (used by both sides)


def today():
    return datetime.now(SGT).date()


def distance_km(lat1, lon1, lat2, lon2):
    # Haversine formula: straight-line distance between two map points in km
    # the formula works in radians, not degrees
    # consulted Claude AI on how to calculate distance between two coordinates in Python
    lat1 = math.radians(float(lat1))
    lon1 = math.radians(float(lon1))
    lat2 = math.radians(float(lat2))
    lon2 = math.radians(float(lon2))
    a = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(a))


def record_update(job, sitter, new_status, note):
    # Save every status change so the owner can see the job's history
    update = SittingUpdate(request=job, sitter=sitter, new_status=new_status, note=note)
    update.save()


# PET SITTER SIDE


# Sitter helpers


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


def email_owner(job, subject, message):
    # Tell the pet owner what happened to their sitting request
    send_mail_in_background(
        subject, message, None, [job.owner.email], fail_silently=True
    )


def owner_rating_summary(owner):
    # average stars sitters gave this pet owner after past jobs, plus the latest comments.
    # Sitters only see the stars, comment and month, not who wrote it.
    rated_jobs = SittingRequest.objects.filter(
        owner=owner, owner_rating__isnull=False
    ).order_by("-end_date")
    total = 0
    comments = []
    for job in rated_jobs:
        total += job.owner_rating
        if job.owner_feedback and len(comments) < 3:
            comments.append(
                {
                    "stars": job.owner_rating,
                    "text": job.owner_feedback,
                    "date": job.end_date,
                }
            )
    count = len(rated_jobs)
    if count == 0:
        return {"average": None, "count": 0, "comments": []}
    return {"average": round(total / count, 1), "count": count, "comments": comments}


# Sign up and application status


def signup(request):
    # A logged-in sitter uses the same form to edit and resubmit the application
    sitter = get_sitter(request)

    if request.method == "GET":
        form = SitterRegistrationForm(sitter=sitter)
        return render(
            request,
            "sitting/signup.html",
            {"form": form, "edit_mode": sitter is not None},
        )

    elif request.method == "POST":
        form = SitterRegistrationForm(request.POST, request.FILES, sitter=sitter)

        if not form.is_valid():
            return render(
                request,
                "sitting/signup.html",
                {"form": form, "edit_mode": sitter is not None},
            )

        new_sitter = form.save()

        # editing an existing application -> back to the status page which application_status.html shows as "Pending" again
        if sitter is not None:
            messages.success(request, "Application updated and sent for review again.")
            return redirect("sitting:application_status")

        # brand-new sitter -> verify the email address first (OTP) before the application is sent to Pawpal for review
        send_otp_code(new_sitter, OTP.Purpose.REGISTER)
        request.session["otp_user_id"] = new_sitter.pk
        request.session["otp_purpose"] = OTP.Purpose.REGISTER
        return redirect("user:verify_otp")


def application_status(request):
    sitter = get_sitter(request)
    if sitter is None:
        return redirect("user:login")

    # The 4 steps of the application. "state" picks the icon and colour in sitter.css:
    # done = green tick, current = orange clock, rejected = red !, waiting = grey dot
    status = sitter.application_status

    if status == PetSitter.Status.PENDING:
        review_state = "current"
    else:
        review_state = "done"

    if status == PetSitter.Status.APPROVED:
        approved_state = "done"
    elif status == PetSitter.Status.REJECTED:
        approved_state = "rejected"
    else:
        approved_state = "waiting"

    # Date Time format: j M Y = 1 Jan 2024, g:i a = 3:45 pm
    applied_at = dateformat.format(
        timezone.localtime(sitter.applied_at), "j M Y, g:i a"
    )
    steps = [
        {
            "title": "Account created & application submitted",
            "note": applied_at,
            "state": "done",
        },
        {"title": "Email verified", "note": "Verification complete", "state": "done"},
        {
            "title": "Under review by Pawpal",
            "note": "Business owner review",
            "state": review_state,
        },
        {
            "title": "Approved — start accepting jobs",
            "note": "",
            "state": approved_state,
        },
    ]

    context = {"sitter": sitter, "steps": steps}
    return render(request, "sitting/application_status.html", context)


# Find jobs


# Sort orders for Find jobs (used with list.sort(key=...))
def earliest_first(job):
    return job.start_date


def nearest_first(job):
    if job.distance is None:
        return 9999  # no map position: show it last
    return job.distance


def sent_to_me_first(job):
    # False comes before True, so jobs sent to me go first
    return not job.sent_to_me


def pet_names(job):
    # e.g. "Mochi, Luna"
    names = []
    for pet in job.pet_list:
        names.append(pet.name)
    return ", ".join(names)


def find_jobs(request):
    sitter = get_approved_sitter(request)
    if sitter is None:
        return redirect("sitting:application_status")

    if request.method == "POST":
        action = request.POST.get("action")
        job_id = request.POST.get("request_id")

        try:
            job = SittingRequest.objects.get(
                pk=job_id, status=SittingRequest.Status.OPEN
            )
        except (SittingRequest.DoesNotExist, ValueError):
            messages.error(request, "This request is no longer open.")
            return redirect("sitting:sitter_find_jobs")

        # a request sent to another sitter cannot be changed by me
        if job.sitter is not None and job.sitter != sitter:
            messages.error(request, "This request was sent to another sitter.")
            return redirect("sitting:sitter_find_jobs")

        if action == "accept":
            # Accepting blocks the job for other sitters.
            # It stays "Pending" until the owner confirms and pays.
            job.sitter = sitter
            job.status = SittingRequest.Status.PENDING
            job.save()
            record_update(
                job,
                sitter,
                SittingRequest.Status.PENDING,
                f"{sitter.first_name} accepted your request.",
            )
            email_owner(
                job,
                "Pawpal: a sitter accepted your request",
                f"{sitter.first_name} accepted your sitting request for "
                f"{job.start_date:%d %b} to {job.end_date:%d %b}. "
                "Please log in to confirm and pay.",
            )
            messages.success(
                request,
                "Job accepted. It is pending until the owner confirms and pays.",
            )
            return redirect("/sitting/my-jobs/?tab=pending")

        elif action == "decline":
            # Only requests sent directly to me can be declined
            if job.sitter != sitter:
                messages.error(request, "Only requests sent to you can be declined.")
                return redirect("sitting:sitter_find_jobs")
            job.status = SittingRequest.Status.DECLINED
            job.save()
            record_update(
                job,
                sitter,
                SittingRequest.Status.DECLINED,
                f"{sitter.first_name} declined your request.",
            )
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
        job.owner_ratings = owner_rating_summary(job.owner)

        # distance from the sitter's service area to the owner's home
        job.distance = None
        if job.latitude and job.longitude and sitter.latitude and sitter.longitude:
            job.distance = round(
                distance_km(
                    sitter.latitude, sitter.longitude, job.latitude, job.longitude
                ),
                1,
            )
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
        job_list.sort(key=earliest_first)
    else:
        job_list.sort(key=nearest_first)
    job_list.sort(key=sent_to_me_first)

    # Data for the map pins (only jobs that have a map position).
    # It is sent to the page with |json_script, so static/sitting/js/jobs_map.js can read it.
    map_pins = []
    for job in job_list:
        if job.latitude and job.longitude:
            map_pins.append(
                {
                    "lat": float(job.latitude),
                    "lng": float(job.longitude),
                    "title": f"{job.owner.first_name} · {job.start_date:%d %b}–{job.end_date:%d %b}",
                    "pets": pet_names(job),
                    "price": job.total_price_display,
                    "distance": job.distance,
                }
            )

    map_centre = None
    if sitter.latitude and sitter.longitude:
        # circle size: the distance filter, or 5 km when "Any"
        radius_km = 5
        if max_distance != "any":
            radius_km = int(max_distance)
        map_centre = {
            "lat": float(sitter.latitude),
            "lng": float(sitter.longitude),
            "label": sitter.service_area,
            "radius_km": radius_km,
        }

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
            job = SittingRequest.objects.get(
                pk=request.POST.get("request_id"), sitter=sitter
            )
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
                email_owner(
                    job,
                    "Pawpal: your pet sitting has started",
                    f"{sitter.first_name} has started looking after your pet.",
                )
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
                messages.success(
                    request,
                    "Job marked as completed. The payout is added to your earnings.",
                )

        elif action == "cancel":
            # an upcoming job the owner already paid for
            if job.status != SittingRequest.Status.ACCEPTED:
                messages.error(request, "Only upcoming jobs can be cancelled.")
            else:
                reason = read_cancel_reason(request)
                job.status = SittingRequest.Status.CANCELLED
                job.cancelled_by = SittingRequest.CancelledBy.SITTER
                job.cancellation_reason = reason
                job.save()
                # the owner already paid for an upcoming job: refund the card and points
                refund_payment(job, label=f"pet sitting #{job.pk}")
                note = f"{sitter.first_name} cancelled the job."
                if reason:
                    note += f" Reason: {reason}"
                record_update(job, sitter, job.status, note)
                email_text = f"{sitter.first_name} cancelled your sitting job. Pawpal has refunded you."
                if reason:
                    email_text += f"\nReason: {reason}"
                email_owner(job, "Pawpal: your sitter cancelled", email_text)
                messages.success(
                    request, "Job cancelled. The owner has been notified and refunded."
                )

        elif action == "withdraw":
            # pending (owner has not confirmed) -> give the request back to other sitters
            if job.status != SittingRequest.Status.PENDING:
                messages.error(request, "Only pending jobs can be withdrawn.")
            else:
                record_update(
                    job,
                    sitter,
                    SittingRequest.Status.OPEN,
                    f"{sitter.first_name} withdrew from this request.",
                )
                job.sitter = None
                job.status = SittingRequest.Status.OPEN
                job.save()
                messages.success(request, "You withdrew from this request.")

        elif action == "update":
            # notes and photos while the job is in progress
            jobs_in_progress = SittingRequest.objects.filter(
                sitter=sitter, status=SittingRequest.Status.IN_PROGRESS
            )
            form = SittingUpdateForm(request.POST, request.FILES, jobs=jobs_in_progress)
            if job.status != SittingRequest.Status.IN_PROGRESS:
                messages.error(
                    request, "Updates can only be posted for jobs in progress."
                )
            elif not form.is_valid():
                show_form_errors(request, form)
            else:
                update = form.save(commit=False)
                update.request = job
                update.sitter = sitter
                update.save()
                messages.success(
                    request,
                    "Update posted. The owner can see it in their booking timeline.",
                )

        elif action == "rate":
            # rate the owner 1-5 stars after the job is completed
            # (each job's form has its own prefix, so the stars of two jobs never mix)
            form = OwnerRatingForm(request.POST, instance=job, prefix=f"job{job.pk}")
            if job.status != SittingRequest.Status.COMPLETED:
                messages.error(
                    request, "You can only rate the owner after the job is completed."
                )
            elif job.owner_rating:
                messages.error(request, "You have already rated this owner.")
            elif not form.is_valid():
                show_form_errors(request, form)
            else:
                form.save()
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
        job.owner_ratings = owner_rating_summary(job.owner)

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
            job.rate_form = OwnerRatingForm(prefix=f"job{job.pk}")
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

    next_job = None
    if upcoming:
        next_job = upcoming[0]

    context = {
        "sitter": sitter,
        "tab": tab,
        # (value, label, how many jobs)
        "tabs": [
            ("all", "All", counts["all"]),
            ("in_progress", "In progress", counts["in_progress"]),
            ("upcoming", "Upcoming", counts["upcoming"]),
            ("pending", "Pending", counts["pending"]),
            ("completed", "Completed", counts["completed"]),
            ("cancelled", "Cancelled", counts["cancelled"]),
        ],
        "counts": counts,
        "in_progress": in_progress,
        "upcoming": upcoming,
        "pending": pending,
        "completed": completed,
        "cancelled": cancelled,
        "timeline": timeline,
        "next_job": next_job,
        "update_form": SittingUpdateForm(jobs=in_progress),
        # auto_id=False: the same box is shown once per job, so it has no id
        "cancel_form": CancelReasonForm(
            placeholder="Reason for cancelling (optional)", auto_id=False
        ),
    }
    return render(request, "sitting/my_jobs.html", context)


# Earnings


def month_before(year, month, count):
    # e.g. month_before(2026, 1, 1) -> (2025, 12)
    total_months = year * 12 + (month - 1) - count
    return total_months // 12, total_months % 12 + 1


def earnings(request):
    sitter = get_approved_sitter(request)
    if sitter is None:
        return redirect("sitting:application_status")

    # date range to show, the same as the business owner's dashboard
    # (default: from the 1st of this month to today)
    try:
        start = date.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        start = today().replace(day=1)
    try:
        end = date.fromisoformat(request.GET.get("end", ""))
    except ValueError:
        end = today()
    if start > end:
        start, end = end, start
        messages.info(request, "Start date was after end date, so they were swapped.")

    completed_jobs = (
        SittingRequest.objects.filter(
            sitter=sitter, status=SittingRequest.Status.COMPLETED
        )
        .select_related("owner")
        .prefetch_related("pets")
        .order_by("-end_date")
    )

    # go through every completed job once and add up the totals
    period_jobs = []
    period_price = 0
    period_commission = 0
    period_payout = 0
    lifetime_payout = 0

    for job in completed_jobs:
        job.pet_list = list(job.pets.all())
        lifetime_payout += job.sitter_payout_cents

        # jobs whose last sitting day is inside the chosen dates
        if start <= job.end_date <= end:
            period_jobs.append(job)
            period_price += job.total_price_cents
            period_commission += job.commission_cents
            period_payout += job.sitter_payout_cents

    # bar chart: payouts for the 6 months up to the end date
    chart = []
    for count in range(5, -1, -1):
        chart_year, chart_month = month_before(end.year, end.month, count)
        total = 0
        for job in completed_jobs:
            if job.end_date.year == chart_year and job.end_date.month == chart_month:
                total += job.sitter_payout_cents
        chart.append(
            {
                "label": datetime(chart_year, chart_month, 1).strftime("%b"),
                "cents": total,
            }
        )

    # the tallest bar sets the scale (at least 1, so we never divide by 0)
    highest = 1
    for bar in chart:
        highest = max(highest, bar["cents"])
    for bar in chart:
        bar["amount"] = f"{bar['cents'] / 100:.0f}"
        bar["height"] = (
            int(bar["cents"] * 160 / highest) + 4
        )  # pixels, +4 so 0 still shows

    # reviews that pet owners wrote about my sitting jobs
    reviews = Review.objects.filter(sitting_request__sitter=sitter).select_related(
        "reviewer"
    )
    rating_total = 0
    for review in reviews:
        rating_total += review.rating
    average_rating = None
    if reviews:
        average_rating = round(rating_total / len(reviews), 1)

    # example breakdown card uses the latest job in the chosen dates
    example_job = None
    if period_jobs:
        example_job = period_jobs[0]

    context = {
        "sitter": sitter,
        "start": start,
        "end": end,
        "period_label": f"{start:%-d %b} – {end:%-d %b %Y}",
        "period_jobs": period_jobs,
        "period_price": f"{period_price / 100:.2f}",
        "period_commission": f"{period_commission / 100:.2f}",
        "period_payout": f"{period_payout / 100:.2f}",
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

    # the three forms on this page (each one has its own Save button)
    profile_form = SitterProfileForm(sitter=sitter)
    account_form = SitterAccountForm(instance=sitter)
    password_form = PasswordChangeForm()

    if request.method == "POST":
        form_name = request.POST.get("form")

        if form_name == "profile":
            # Sitter profile: what pet owners see
            profile_form = SitterProfileForm(request.POST, request.FILES, sitter=sitter)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Sitter profile saved.")
                return redirect("sitting:sitter_profile")

        elif form_name == "account":
            # Account details
            account_form = SitterAccountForm(request.POST, instance=sitter)
            if account_form.is_valid():
                account_form.save()
                request.session["username"] = sitter.first_name
                messages.success(request, "Account details updated.")
                return redirect("sitting:sitter_profile")

        elif form_name == "password":
            # Change password: current one must be correct first
            password_form = PasswordChangeForm(request.POST)
            if password_form.is_valid():
                if sitter.check_password(
                    password_form.cleaned_data["current_password"]
                ):
                    sitter.set_password(password_form.cleaned_data["new_password"])
                    sitter.save()
                    messages.success(request, "Password changed.")
                    return redirect("sitting:sitter_profile")
                password_form.add_error(
                    "current_password", "Your current password is incorrect."
                )

        # a form had a mistake: show the page again with the error under the box

    reviews = Review.objects.filter(sitting_request__sitter=sitter)
    rating_total = 0
    for review in reviews:
        rating_total += review.rating
    average_rating = None
    if reviews:
        average_rating = round(rating_total / len(reviews), 1)

    jobs_done = SittingRequest.objects.filter(
        sitter=sitter, status=SittingRequest.Status.COMPLETED
    ).count()

    context = {
        "sitter": sitter,
        "profile_form": profile_form,
        "account_form": account_form,
        "password_form": password_form,
        "average_rating": average_rating,
        "jobs_done": jobs_done,
        # what the sitter receives per day after Pawpal's 10% commission
        "daily_payout": f"{sitter.daily_rate_cents * 0.9 / 100:.2f}",
    }
    return render(request, "sitting/profile.html", context)


# PET OWNER (CUSTOMER) SIDE


# Find a pet sitter


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
    # Read and check the "Your request" form.
    # Gives back (form_values, errors).
    # form_values keeps what the user typed, so the form can show it again.
    # When the form is valid, it also has the real objects (pets, address).
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
        values["address"] = Address.objects.get(
            pk=values["address_id"], customer=customer
        )
    except (Address.DoesNotExist, ValueError):
        errors.append("Choose the location (one of your saved addresses).")

    # only the customer's own pets can be chosen
    pet_ids = []
    for pet_id in values["pet_ids"]:
        if pet_id.isdigit():
            pet_ids.append(pet_id)
    values["pets"] = list(Pet.objects.filter(owner_id=customer, pk__in=pet_ids))
    if not values["pets"]:
        errors.append("Choose at least one pet that needs care.")

    return values, errors


def sitter_score(sitter):
    return sitter.score


def recommend_sitters(values, latitude, longitude):
    # Rank the approved sitters who are free for this request.
    # score = rating x 2
    #         + 2 for each pet type they have looked after
    #         + 1.5 for each finished job with the same breed
    #         - distance (km) / 2
    breeds = []
    for pet in values["pets"]:
        if pet.breed:
            breeds.append(pet.breed)
    results = []

    for sitter in PetSitter.objects.filter(
        application_status=PetSitter.Status.APPROVED, is_active=True
    ):
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
            sitter.distance = round(
                distance_km(latitude, longitude, sitter.latitude, sitter.longitude), 1
            )

        sitter.rating, sitter.review_count = sitter_rating(sitter)

        experience = sitter.pet_experience.lower()
        type_matches = 0
        for pet in values["pets"]:
            if PET_TYPE_WORDS.get(pet.pet_type, "") in experience:
                type_matches += 1

        sitter.breed_jobs = 0
        if breeds:
            sitter.breed_jobs = (
                SittingRequest.objects.filter(
                    sitter=sitter,
                    status=SittingRequest.Status.COMPLETED,
                    pets__breed__in=breeds,
                )
                .distinct()
                .count()
            )

        sitter.score = (
            (sitter.rating or 0) * 2 + type_matches * 2 + sitter.breed_jobs * 1.5
        )
        if sitter.distance is not None:
            sitter.score -= sitter.distance / 2
        else:
            sitter.score -= 5  # no map position: treat as 10 km away

        sitter.price = f"{sitter.daily_rate_cents * values['days'] / 100:.2f}"
        results.append(sitter)

    results.sort(key=sitter_score, reverse=True)
    return results


def approved_daily_rates():
    # the daily rate (in cents) of every approved sitter
    rates = []
    for sitter in PetSitter.objects.filter(
        application_status=PetSitter.Status.APPROVED
    ):
        rates.append(sitter.daily_rate_cents)
    return rates


def find_sitter(request):
    customer = get_current_customer(request)
    if customer is None:
        return redirect("user:login")

    addresses = Address.objects.filter(customer=customer).order_by(
        "-is_default", "label"
    )
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
            location=f"{address.line1} {address.line2}, Singapore {address.postal_code}".replace(
                "  ", " "
            ),
            latitude=latitude,
            longitude=longitude,
            care_requirements=values["care"],
            status=SittingRequest.Status.OPEN,
        )

        if request.POST.get("action") == "send":
            # send to the sitter the owner picked
            try:
                sitter = PetSitter.objects.get(
                    pk=request.POST.get("sitter_id"),
                    application_status=PetSitter.Status.APPROVED,
                )
            except (PetSitter.DoesNotExist, ValueError):
                messages.error(request, "That sitter is not available.")
                return redirect("sitting:find_sitter")
            new_request.sitter = sitter
            new_request.total_price_cents = sitter.daily_rate_cents * values["days"]
        else:
            # open request: every nearby sitter can see it in Find Jobs.
            # Price estimate = average daily rate of approved sitters.
            rates = approved_daily_rates()
            average_rate = 5000  # $50 a day when there are no sitters yet
            if rates:
                average_rate = sum(rates) // len(rates)
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
            messages.success(
                request,
                f"Request sent to {new_request.sitter.first_name}. We'll email you when they reply.",
            )
        else:
            messages.success(
                request, "Request posted. Nearby sitters can now accept it."
            )
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
            rates = approved_daily_rates()
            if rates:
                estimate = {
                    "days": values["days"],
                    "low": f"{min(rates) * values['days'] / 100:.0f}",
                    "high": f"{max(rates) * values['days'] / 100:.0f}",
                }

    # pre-select the default address the first time
    if not values.get("address_id"):
        default_address = addresses.first()
        values["address_id"] = ""
        if default_address:
            values["address_id"] = str(default_address.pk)

    my_requests = (
        SittingRequest.objects.filter(owner=customer)
        .select_related("sitter")
        .order_by("-created_at")[:3]
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
    customer = get_current_customer(request)
    if customer is None:
        return redirect("user:login")

    try:
        sitter = PetSitter.objects.get(
            pk=pk, application_status=PetSitter.Status.APPROVED
        )
    except PetSitter.DoesNotExist:
        messages.error(request, "Sitter not found.")
        return redirect("sitting:find_sitter")

    rating, review_count = sitter_rating(sitter)
    reviews = Review.objects.filter(sitting_request__sitter=sitter).select_related(
        "reviewer"
    )[:10]
    jobs_done = SittingRequest.objects.filter(
        sitter=sitter, status=SittingRequest.Status.COMPLETED
    ).count()

    context = {
        "sitter": sitter,
        "rating": rating,
        "review_count": review_count,
        "reviews": reviews,
        "jobs_done": jobs_done,
        "query_string": request.GET.urlencode(),
    }
    return render(request, "sitting/sitter_public_profile.html", context)


# My sitting requests


def my_sitting_requests(request):
    # "View all" list of the customer's sitting requests
    customer = get_current_customer(request)
    if customer is None:
        return redirect("user:login")

    requests_list = (
        SittingRequest.objects.filter(owner=customer)
        .select_related("sitter")
        .prefetch_related("pets")
        .order_by("-created_at")
    )
    return render(
        request, "sitting/my_sitting_requests.html", {"requests_list": requests_list}
    )


# Customers can cancel a sitting request until the day the sitting starts
def sitting_cancel_deadline(job):
    return datetime.combine(
        job.start_date, time.min, tzinfo=SGT
    )  # 12:00 am on the first day


def sitting_can_cancel(job):
    not_started = job.status in [
        SittingRequest.Status.OPEN,
        SittingRequest.Status.PENDING,
        SittingRequest.Status.ACCEPTED,
    ]
    return not_started and datetime.now(SGT) < sitting_cancel_deadline(job)


def request_detail(request, pk):
    # Track the status, see the sitter's notes and photos, cancel, or review
    customer = get_current_customer(request)
    if customer is None:
        return redirect("user:login")

    try:
        job = SittingRequest.objects.select_related("sitter").get(pk=pk, owner=customer)
    except SittingRequest.DoesNotExist:
        messages.error(request, "Sitting request not found.")
        return redirect("sitting:my_sitting_requests")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "review":
            # Add a review, or update my review if I already wrote one
            if job.status != SittingRequest.Status.COMPLETED:
                messages.error(
                    request, "You can review the sitter after the job is completed."
                )
                return redirect("sitting:request_detail", pk=job.pk)

            my_review = Review.objects.filter(
                sitting_request=job, reviewer=customer
            ).first()
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
                return render_request_detail(
                    request, job, customer, review_form=form, editing=True
                )

        elif action == "delete_review":
            my_review = Review.objects.filter(
                sitting_request=job, reviewer=customer
            ).first()
            if my_review is None:
                messages.error(request, "There is no review to delete.")
            else:
                my_review.delete()
                messages.success(request, "Your review was deleted.")

        else:
            messages.error(request, "Unknown action.")

        return redirect("sitting:request_detail", pk=job.pk)

    # ?edit=1 opens the form again to change an existing review
    return render_request_detail(
        request, job, customer, editing=request.GET.get("edit") == "1"
    )


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
    # which step the request is at (-1 when it is cancelled or declined)
    current_index = -1
    for i in range(len(steps)):
        if steps[i][0] == job.status:
            current_index = i

    payment = job.payments.order_by("-created_at").first()
    paid_amount = None
    if payment:
        paid_amount = f"{payment.amount_cents / 100:.2f}"

    # Same cancel section as bookings and orders (user/_cancel_section.html)
    allowed = sitting_can_cancel(job)
    not_started = job.status in [
        SittingRequest.Status.OPEN,
        SittingRequest.Status.PENDING,
        SittingRequest.Status.ACCEPTED,
    ]
    paid_cents = 0
    if payment and payment.status == "COMPLETED":
        paid_cents = payment.amount_cents

    context = {
        "can_cancel": allowed,
        "confirm_cancel": allowed and request.GET.get("cancel") == "1",
        # shown as Singapore time (settings.py uses UTC, which would show 4:00 PM the day before)
        "cancel_deadline": sitting_cancel_deadline(job).replace(tzinfo=None),
        "cancel_closed": not_started and not allowed,
        "cancel_form": CancelReasonForm(),
        "refund_dollars": paid_cents / 100,
        "not_paid": paid_cents == 0,
        "job": job,
        "pets": job.pets.all(),
        "updates": SittingUpdate.objects.filter(request=job),
        "steps": steps,
        "current_index": current_index,
        "my_review": my_review,
        "review_form": review_form,
        # show the form when there is no review yet, or when editing it
        "show_review_form": job.status == SittingRequest.Status.COMPLETED
        and (my_review is None or editing),
        "payment": payment,
        "paid_amount": paid_amount,
    }
    return render(request, "sitting/request_detail.html", context)


def cancel_request(request, pk):
    # "Yes, cancel sitting request" button on the request page
    customer = get_current_customer(request)
    if customer is None:
        return redirect("user:login")
    if request.method != "POST":
        return redirect("sitting:request_detail", pk=pk)

    try:
        job = SittingRequest.objects.select_related("sitter").get(pk=pk, owner=customer)
    except SittingRequest.DoesNotExist:
        messages.error(request, "Sitting request not found.")
        return redirect("sitting:my_sitting_requests")

    if not sitting_can_cancel(job):
        messages.error(
            request,
            "This sitting request can no longer be cancelled. Please contact Pawpal.",
        )
        return redirect("sitting:request_detail", pk=job.pk)

    reason = read_cancel_reason(request)
    job.status = SittingRequest.Status.CANCELLED
    job.cancelled_by = SittingRequest.CancelledBy.CUSTOMER
    job.cancellation_reason = reason
    job.save()

    # if the owner already paid: refund the card and give back the points (same as orders and bookings)
    refund_payment(job, label=f"pet sitting #{job.pk}")

    if job.sitter:
        note = f"{customer.first_name} cancelled this request."
        if reason:
            note += f" Reason: {reason}"
        record_update(job, job.sitter, job.status, note)
        email_text = f"{customer.first_name} cancelled the request for {job.start_date:%d %b} to {job.end_date:%d %b}."
        if reason:
            email_text += f"\nReason: {reason}"
        send_mail_in_background(
            "Pawpal: a sitting request was cancelled",
            email_text,
            None,
            [job.sitter.email],
            fail_silently=True,
        )

    messages.success(request, "Your sitting request has been cancelled.")
    return redirect("sitting:request_detail", pk=job.pk)


def pay_for_request(request, pk):
    # The sitter accepted (status "pending") -> the owner confirms and pays
    customer = get_current_customer(request)
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
    form, preview_points = bind_checkout_form(
        request, PaymentDetailsForm, customer, points_balance
    )

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
        record_update(
            job, job.sitter, job.status, f"{customer.first_name} confirmed and paid."
        )
        send_mail_in_background(
            "Pawpal: sitting job confirmed",
            f"{customer.first_name} confirmed and paid for {job.start_date:%d %b} to {job.end_date:%d %b}. "
            "It is now in your Upcoming jobs.",
            None,
            [job.sitter.email],
            fail_silently=True,
        )
        messages.success(
            request, f"Paid! {job.sitter.first_name} is confirmed for your pet sitting."
        )
        return redirect("sitting:request_detail", pk=job.pk)

    discount_cents = calculate_points_discount(
        job.total_price_cents, preview_points, points_balance
    )
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
