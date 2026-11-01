from django.shortcuts import render, HttpResponse

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