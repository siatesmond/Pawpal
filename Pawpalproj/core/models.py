from django.db import models


# Create your models here.
class Outlet(models.Model):
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    postal_code = models.CharField(max_length=6)
    phone = models.CharField(max_length=8)
    opening_time = models.DateTimeField()
    closing_time = models.DateTimeField()
    is_active = models.BooleanField()
