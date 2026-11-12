# Helpers that any app can use, e.g. from user.utils import get_current_customer

import threading

from django.contrib import messages
from django.core.mail import send_mail

from .models import Customer


def get_current_customer(request):
    # The logged-in customer, or None for guests and other user types
    user_id = request.session.get("user_id")
    if user_id is None or request.session.get("user_type") != "customer":
        return None
    return Customer.objects.filter(pk=user_id).first()


def show_form_errors(request, form):
    # For pages that go straight back to a list after a small form:
    # show the form's mistakes as messages at the top of the page
    for field_errors in form.errors.values():
        for error in field_errors:
            messages.error(request, error)


def send_mail_in_background(subject, message, from_email, recipient_list, fail_silently=True):
    # Same as Django's send_mail(), but the page does not wait for the email.
    # Gmail takes about 4 seconds to send, so the email is sent in a separate thread
    # and the page can move on straight away.
    email_thread = threading.Thread(
        target=send_mail,
        args=(subject, message, from_email, recipient_list),
        kwargs={"fail_silently": fail_silently},
        daemon=True,  # don't keep the server running just for an email
    )
    email_thread.start()
