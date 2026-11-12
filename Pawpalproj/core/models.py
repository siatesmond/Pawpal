from django.db import models


# Models in this file:
# Outlet  (a Pawpal shop: where services happen and orders are picked up)


class Outlet(models.Model):
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    postal_code = models.CharField(max_length=6)
    phone = models.CharField(max_length=8)
    opening_time = models.DateTimeField()
    closing_time = models.DateTimeField()
    is_active = models.BooleanField()

    def __str__(self):
        return self.name
