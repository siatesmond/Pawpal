"""
Shared session helpers – any app can import these.

    from user.utils import get_current_customer
"""

import threading

from django.core.mail import send_mail

from .models import Customer


def get_current_customer(request):
    """The logged-in Customer (from the session), or None for guests / other roles."""
    user_id = request.session.get("user_id")
    if user_id is None or request.session.get("user_type") != "customer":
        return None
    return Customer.objects.filter(pk=user_id).first()


def send_mail_in_background(subject, message, from_email, recipient_list, fail_silently=True):
    """Same as Django's send_mail, but the page does not wait for it.

    Sending through Gmail takes about 4 seconds, so we send the email in a
    separate thread and let the page redirect straight away.
    """
    email_thread = threading.Thread(
        target=send_mail,
        args=(subject, message, from_email, recipient_list),
        kwargs={"fail_silently": fail_silently},
        daemon=True,  # don't keep the server running just for an email
    )
    email_thread.start()
