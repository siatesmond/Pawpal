"""
Shared session helpers – any app can import these.

    from user.utils import get_current_customer
"""

from .models import Customer


def get_current_customer(request):
    """The logged-in Customer (from the session), or None for guests / other roles."""
    user_id = request.session.get("user_id")
    if user_id is None or request.session.get("user_type") != "customer":
        return None
    return Customer.objects.filter(pk=user_id).first()
