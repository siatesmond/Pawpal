import csv
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth.hashers import make_password
from django.db.models import Count, F, Q, Sum
from django.contrib import messages
from user.utils import send_mail_in_background
from django.shortcuts import HttpResponse, get_object_or_404, redirect, render
from django.utils import timezone
from inventory.models import Brand, CartItem, Category, Order, OrderItem, Product
from payment.models import Payment, PointsTransaction
from payment.services import add_points
from review.models import Review
from service.models import Booking, BookingUpdate, Service, TimeSlot
from sitting.models import PetSitter, SittingRequest, SittingUpdate
from user.models import Address, BusinessOwner, Customer, Pet, Staff, User

from core.models import Outlet
from .forms import OwnerCustomerForm, OwnerStaffEditForm, OwnerStaffForm

# Helpers

SGT = ZoneInfo("Asia/Singapore")
DEMO_PASSWORD = "Pawpal123!"  # every demo account uses this password
OWNER_PASSWORD = os.getenv("PAWPAL_OWNER_PASSWORD", DEMO_PASSWORD)
STAFF_PASSWORD = os.getenv("PAWPAL_STAFF_PASSWORD", DEMO_PASSWORD)


def today():
    return datetime.now(SGT).date()


def sg_datetime(day_offset, hhmm):
    """day_offset days from today at HH:MM Singapore time, e.g. (2, "10:00")."""
    day = today() + timedelta(days=day_offset)
    return datetime.combine(day, time.fromisoformat(hhmm), tzinfo=SGT)


def days_ago(n):
    return timezone.now() - timedelta(days=n)


def outlet_time(hhmm):
    """Works whether Outlet.opening_time is a TimeField or a DateTimeField."""
    if Outlet._meta.get_field("opening_time").get_internal_type() == "TimeField":
        return time.fromisoformat(hhmm)
    return sg_datetime(0, hhmm)


def set_created_at(model, pk, n_days_ago):
    """auto_now_add always saves 'now', so move the date back afterwards."""
    model.objects.filter(pk=pk).update(created_at=days_ago(n_days_ago))


# Mock data – core

outlets = [
    {
        "name": "Pawpal Tampines",
        "address": "10 Tampines Central 1, #01-15",
        "postal_code": "529536",
        "phone": "61234501",
        "opening_time": "09:00",
        "closing_time": "21:00",
        "is_active": True,
    },
    {
        "name": "Pawpal Jurong East",
        "address": "50 Jurong Gateway Road, #02-08",
        "postal_code": "608549",
        "phone": "61234502",
        "opening_time": "10:00",
        "closing_time": "22:00",
        "is_active": True,
    },
    {
        "name": "Pawpal Bishan",
        "address": "9 Bishan Place, #01-30",
        "postal_code": "579837",
        "phone": "61234503",
        "opening_time": "09:00",
        "closing_time": "20:00",
        "is_active": True,
    },
    {
        "name": "Pawpal Holland Village",
        "address": "211 Holland Avenue, #01-02",
        "postal_code": "278967",
        "phone": "61234504",
        "opening_time": "10:00",
        "closing_time": "19:00",
        "is_active": False,
    },  # renovation
]

# Mock data – users

business_owners = [
    {
        "username": "owner_lim",
        "email": "pawpal.sg.demo@gmail.com",
        "first_name": "Grace",
        "last_name": "Tan",
        "mobile": "91234567",
    },
]

staff_members = [
    {
        "username": "staff_test",
        "email": "staff_test@pawpal.local",
        "first_name": "Staff",
        "last_name": "Test",
        "mobile": "90000000",
        "outlet": "Pawpal Tampines",
        "password": STAFF_PASSWORD,
    },
    {
        "username": "staff_sarah",
        "email": "sarah@pawpal.sg",
        "first_name": "Sarah",
        "last_name": "Goh",
        "mobile": "92345678",
        "outlet": "Pawpal Tampines",
    },
    {
        "username": "staff_ravi",
        "email": "ravi@pawpal.sg",
        "first_name": "Ravi",
        "last_name": "Kumar",
        "mobile": "92345679",
        "outlet": "Pawpal Tampines",
    },
    {
        "username": "staff_mei",
        "email": "mei@pawpal.sg",
        "first_name": "Mei Ling",
        "last_name": "Chua",
        "mobile": "92345680",
        "outlet": "Pawpal Jurong East",
    },
    {
        "username": "staff_daniel",
        "email": "daniel@pawpal.sg",
        "first_name": "Daniel",
        "last_name": "Teo",
        "mobile": "92345681",
        "outlet": "Pawpal Bishan",
    },
]

customers = [
    {
        "username": "amy_tan",
        "email": "amy.tan@example.com",
        "first_name": "Amy",
        "last_name": "Tan",
        "mobile": "81234567",
        "is_verified": True,
    },
    {
        "username": "jason_lee",
        "email": "jason.lee@example.com",
        "first_name": "Jason",
        "last_name": "Lee",
        "mobile": "81234568",
        "is_verified": True,
    },
    {
        "username": "nur_aisyah",
        "email": "nur.aisyah@example.com",
        "first_name": "Nur",
        "last_name": "Aisyah",
        "mobile": "81234569",
        "is_verified": True,
    },
    {
        "username": "kumar_r",
        "email": "kumar.r@example.com",
        "first_name": "Kumar",
        "last_name": "Rajan",
        "mobile": "81234570",
        "is_verified": True,
    },
    {
        "username": "chloe_ng",
        "email": "chloe.ng@example.com",
        "first_name": "Chloe",
        "last_name": "Ng",
        "mobile": "81234571",
        "is_verified": True,
    },
    # brand-new customer: no pets, bookings or orders (for the empty-state home page C1b)
    {
        "username": "ben_wong",
        "email": "ben.wong@example.com",
        "first_name": "Ben",
        "last_name": "Wong",
        "mobile": "81234572",
        "is_verified": True,
    },
    # signed up but has not entered the OTP yet
    {
        "username": "zoe_lim",
        "email": "zoe.lim@example.com",
        "first_name": "Zoe",
        "last_name": "Lim",
        "mobile": "81234573",
        "is_verified": False,
    },
]

pet_sitters = [
    {
        "username": "sitter_grace",
        "email": "grace@example.com",
        "first_name": "Grace",
        "last_name": "Koh",
        "mobile": "83456789",
        "bio": "Lifelong animal lover and former vet clinic assistant.",
        "postal_code": "520201",
        "service_area": "Tampines Street 21",
        "latitude": "1.352895",
        "longitude": "103.953586",
        "experience_years": 5,
        "pet_experience": "dogs, cats",
        "daily_rate_cents": 6000,
        "application_status": "APPROVED",
        "rejection_reason": "",
        "reviewed_by": "owner_lim",
    },
    {
        "username": "sitter_hafiz",
        "email": "hafiz@example.com",
        "first_name": "Hafiz",
        "last_name": "Rahman",
        "mobile": "83456790",
        "bio": "Dog walker who loves big, energetic breeds.",
        "postal_code": "600135",
        "service_area": "Jurong Gateway Road",
        "latitude": "1.333825",
        "longitude": "103.739677",
        "experience_years": 3,
        "pet_experience": "dogs",
        "daily_rate_cents": 5000,
        "application_status": "APPROVED",
        "rejection_reason": "",
        "reviewed_by": "owner_lim",
    },
    {
        "username": "sitter_emily",
        "email": "emily@example.com",
        "first_name": "Emily",
        "last_name": "Sim",
        "mobile": "83456791",
        "bio": "University student with two cats at home.",
        "postal_code": "579837",
        "service_area": "Bishan Place",
        "latitude": "1.350422",
        "longitude": "103.848826",
        "experience_years": 1,
        "pet_experience": "cats",
        "daily_rate_cents": 4500,
        "application_status": "PENDING",
        "rejection_reason": "",
        "reviewed_by": None,
    },
    {
        "username": "sitter_marcus",
        "email": "marcus@example.com",
        "first_name": "Marcus",
        "last_name": "Yeo",
        "mobile": "83456792",
        "bio": "Happy to look after any pet.",
        "postal_code": "730888",
        "service_area": "Woodlands Drive 50",
        "latitude": "1.437705",
        "longitude": "103.795269",
        "experience_years": 0,
        "pet_experience": "dogs, cats, rabbits",
        "daily_rate_cents": 3500,
        "application_status": "REJECTED",
        "rejection_reason": "ID document was unclear. Please re-apply with a clearer photo.",
        "reviewed_by": "owner_lim",
    },
]

addresses = [
    {
        "customer": "amy_tan",
        "line1": "Blk 123 Tampines Street 11",
        "line2": "#05-67",
        "postal_code": "521123",
    },
    {
        "customer": "amy_tan",
        "line1": "1 Raffles Place",
        "line2": "#20-01 (Office)",
        "postal_code": "048616",
    },
    {
        "customer": "jason_lee",
        "line1": "Blk 250 Jurong East Street 24",
        "line2": "#08-12",
        "postal_code": "600250",
    },
    {
        "customer": "nur_aisyah",
        "line1": "Blk 456 Bishan Street 13",
        "line2": "#11-20",
        "postal_code": "570456",
    },
    {
        "customer": "kumar_r",
        "line1": "18 Holland Grove Road",
        "line2": "",
        "postal_code": "278806",
    },
    {
        "customer": "chloe_ng",
        "line1": "Blk 789 Woodlands Drive 50",
        "line2": "#03-15",
        "postal_code": "730789",
    },
]

pets = [
    {
        "owner": "amy_tan",
        "name": "Mochi",
        "pet_type": "DOG",
        "breed": "Shiba Inu",
        "date_of_birth": date(2023, 8, 14),
        "weight_kg": Decimal("9.50"),
        "medical_notes": "Mild seasonal skin allergies. Uses medicated shampoo monthly.",
        "behaviour_notes": "Independent and a bit stubborn. Dislikes nail trimming; use treats and go slowly.",
        "last_vaccination_date": date(2026, 3, 12),
    },
    {
        "owner": "amy_tan",
        "name": "Luna",
        "pet_type": "CAT",
        "breed": "British Shorthair",
        "date_of_birth": date(2024, 5, 3),
        "weight_kg": Decimal("4.80"),
        "medical_notes": "",
        "behaviour_notes": "Calm, but gets stressed in carriers. Prefers a towel over the carrier.",
        "last_vaccination_date": date(2026, 5, 20),
    },
    {
        "owner": "jason_lee",
        "name": "Bobby",
        "pet_type": "DOG",
        "breed": "Golden Retriever",
        "date_of_birth": date(2021, 9, 27),
        "weight_kg": Decimal("31.20"),
        "medical_notes": "Early-stage hip dysplasia. Joint supplement daily. Avoid long stair climbs.",
        "behaviour_notes": "Very friendly and food-motivated. Tends to jump up when excited.",
        "last_vaccination_date": date(2026, 1, 15),
    },
    {
        "owner": "nur_aisyah",
        "name": "Kopi",
        "pet_type": "CAT",
        "breed": "Domestic Short Hair",
        "date_of_birth": date(2022, 6, 9),
        "weight_kg": Decimal("4.20"),
        "medical_notes": "Allergic to chicken-based food. Feed fish or turkey formulas only.",
        "behaviour_notes": "Shy with strangers; hides under furniture. Approach slowly and let her come to you.",
        "last_vaccination_date": date(2025, 11, 30),
    },
    {
        "owner": "nur_aisyah",
        "name": "Snowy",
        "pet_type": "CAT",
        "breed": "Persian",
        "date_of_birth": date(2020, 12, 1),
        "weight_kg": Decimal("5.10"),
        "medical_notes": "Chronic eye discharge (needs daily wiping). Prone to hairballs.",
        "behaviour_notes": "Gentle but dislikes being brushed around the belly. Short grooming sessions work best.",
        "last_vaccination_date": date(2026, 2, 8),
    },
    {
        "owner": "kumar_r",
        "name": "Milo",
        "pet_type": "DOG",
        "breed": "Beagle",
        "date_of_birth": date(2019, 10, 18),
        "weight_kg": Decimal("12.75"),
        "medical_notes": "On heart medication (twice daily). Senior dog; avoid strenuous exercise.",
        "behaviour_notes": "Howls when left alone. Will follow food smells, so keep treats out of reach.",
        "last_vaccination_date": date(2026, 4, 2),
    },
    {
        "owner": "chloe_ng",
        "name": "Coco",
        "pet_type": "DOG",
        "breed": "Maltese",
        "date_of_birth": date(2024, 7, 22),
        "weight_kg": Decimal("3.40"),
        "medical_notes": "Sensitive stomach. Tear staining; clean around eyes regularly.",
        "behaviour_notes": "Barks at loud noises and unfamiliar dogs. Handle gently, small and fragile.",
        "last_vaccination_date": date(2026, 6, 10),
    },
    {
        "owner": "chloe_ng",
        "name": "Tofu",
        "pet_type": "OTHER",
        "breed": "Holland Lop Rabbit",
        "date_of_birth": date(2025, 9, 5),
        "weight_kg": Decimal("1.60"),
        "medical_notes": "Watch for dental overgrowth; provide hay at all times.",
        "behaviour_notes": "Skittish when picked up. Support the hindquarters and avoid sudden movements.",
        "last_vaccination_date": None,
    },
]
# Mock data – inventory

categories = ["Food", "Treats", "Toys", "Grooming", "Accessories", "Health"]
brands = [
    "NutriPaws",
    "Whisker & Co",
    "Happy Tails",
    "FurFresh",
    "PlayPup",
    "VetCare",
]  # fictional

products = [
    {
        "name": "Grain-Free Salmon Kibble 2kg",
        "category": "Food",
        "brand": "NutriPaws",
        "pet_type": "DOG",
        "description": "High-protein dry food with real salmon for adult dogs.",
        "price_cents": 3990,
        "stock_quantity": 40,
        "low_stock_level": 10,
        "is_active": True,
    },
    {
        "name": "Puppy Chicken & Rice 1.5kg",
        "category": "Food",
        "brand": "NutriPaws",
        "pet_type": "DOG",
        "description": "Gentle on tummies, made for puppies up to 12 months.",
        "price_cents": 2850,
        "stock_quantity": 25,
        "low_stock_level": 8,
        "is_active": True,
    },
    {
        "name": "Tuna Pâté Wet Food (12 cans)",
        "category": "Food",
        "brand": "Whisker & Co",
        "pet_type": "CAT",
        "description": "Smooth tuna pâté in 85g cans, complete and balanced.",
        "price_cents": 2400,
        "stock_quantity": 4,
        "low_stock_level": 5,
        "is_active": True,
    },  # low stock
    {
        "name": "Indoor Cat Dry Food 1.2kg",
        "category": "Food",
        "brand": "Whisker & Co",
        "pet_type": "CAT",
        "description": "Hairball control formula for indoor cats.",
        "price_cents": 2290,
        "stock_quantity": 30,
        "low_stock_level": 8,
        "is_active": True,
    },
    {
        "name": "Chicken Jerky Strips 200g",
        "category": "Treats",
        "brand": "Happy Tails",
        "pet_type": "DOG",
        "description": "Air-dried chicken breast strips, no preservatives.",
        "price_cents": 1290,
        "stock_quantity": 60,
        "low_stock_level": 10,
        "is_active": True,
    },
    {
        "name": "Lickable Cat Treats (20 tubes)",
        "category": "Treats",
        "brand": "Whisker & Co",
        "pet_type": "CAT",
        "description": "Creamy chicken treats cats can lick straight from the tube.",
        "price_cents": 1590,
        "stock_quantity": 0,
        "low_stock_level": 5,
        "is_active": True,
    },  # out of stock
    {
        "name": "Dental Chew Sticks (7 pcs)",
        "category": "Treats",
        "brand": "Happy Tails",
        "pet_type": "DOG",
        "description": "Helps reduce plaque and freshen breath.",
        "price_cents": 990,
        "stock_quantity": 35,
        "low_stock_level": 10,
        "is_active": True,
    },
    {
        "name": "Rope Tug Toy",
        "category": "Toys",
        "brand": "PlayPup",
        "pet_type": "DOG",
        "description": "Durable cotton rope for tug-of-war and chewing.",
        "price_cents": 890,
        "stock_quantity": 22,
        "low_stock_level": 5,
        "is_active": True,
    },
    {
        "name": "Feather Wand Teaser",
        "category": "Toys",
        "brand": "PlayPup",
        "pet_type": "CAT",
        "description": "Interactive feather wand to keep cats active.",
        "price_cents": 690,
        "stock_quantity": 3,
        "low_stock_level": 5,
        "is_active": True,
    },  # low stock
    {
        "name": "Squeaky Plush Duck",
        "category": "Toys",
        "brand": "PlayPup",
        "pet_type": "DOG",
        "description": "Soft plush toy with a squeaker inside.",
        "price_cents": 1190,
        "stock_quantity": 15,
        "low_stock_level": 5,
        "is_active": False,
    },  # discontinued
    {
        "name": "Oatmeal Pet Shampoo 500ml",
        "category": "Grooming",
        "brand": "FurFresh",
        "pet_type": "OTHER",
        "description": "Soothing oatmeal shampoo for dogs, cats and small pets.",
        "price_cents": 1650,
        "stock_quantity": 28,
        "low_stock_level": 6,
        "is_active": True,
    },
    {
        "name": "Slicker Brush",
        "category": "Grooming",
        "brand": "FurFresh",
        "pet_type": "OTHER",
        "description": "Removes loose fur and tangles for all coat types.",
        "price_cents": 1490,
        "stock_quantity": 18,
        "low_stock_level": 5,
        "is_active": True,
    },
    {
        "name": "Reflective Dog Leash 1.5m",
        "category": "Accessories",
        "brand": "Happy Tails",
        "pet_type": "DOG",
        "description": "Padded handle with reflective stitching for night walks.",
        "price_cents": 1990,
        "stock_quantity": 20,
        "low_stock_level": 5,
        "is_active": True,
    },
    {
        "name": "Breakaway Cat Collar",
        "category": "Accessories",
        "brand": "Whisker & Co",
        "pet_type": "CAT",
        "description": "Safety buckle releases if the collar gets caught.",
        "price_cents": 790,
        "stock_quantity": 26,
        "low_stock_level": 5,
        "is_active": True,
    },
    {
        "name": "Joint Support Supplement (60 tabs)",
        "category": "Health",
        "brand": "VetCare",
        "pet_type": "DOG",
        "description": "Glucosamine and omega-3 for healthy joints.",
        "price_cents": 3290,
        "stock_quantity": 12,
        "low_stock_level": 4,
        "is_active": True,
    },
    {
        "name": "Flea & Tick Spot-On (3 doses)",
        "category": "Health",
        "brand": "VetCare",
        "pet_type": "CAT",
        "description": "Monthly spot-on treatment for cats over 1kg.",
        "price_cents": 2690,
        "stock_quantity": 9,
        "low_stock_level": 4,
        "is_active": True,
    },
]

cart_items = [
    {"customer": "amy_tan", "product": "Dental Chew Sticks (7 pcs)", "quantity": 2},
    {"customer": "amy_tan", "product": "Breakaway Cat Collar", "quantity": 1},
    {"customer": "chloe_ng", "product": "Reflective Dog Leash 1.5m", "quantity": 1},
]

DELIVERY_FEE_CENTS = 500

# "ref" is only used inside loadData to link payments and reviews to this order
orders = [
    {
        "ref": "O1",
        "customer": "amy_tan",
        "pickup_outlet": None,
        "delivery_address": "Blk 123 Tampines Street 11",
        "est_delivery_in_days": -17,
        "status": "COMPLETED",
        "points_discount_cents": 0,
        "days_ago": 20,
        "items": [
            ("Grain-Free Salmon Kibble 2kg", 1),
            ("Chicken Jerky Strips 200g", 2),
        ],
    },
    {
        "ref": "O2",
        "customer": "jason_lee",
        "pickup_outlet": "Pawpal Jurong East",
        "delivery_address": None,
        "est_delivery_in_days": None,
        "status": "COMPLETED",
        "points_discount_cents": 0,
        "days_ago": 12,
        "items": [("Rope Tug Toy", 1), ("Dental Chew Sticks (7 pcs)", 2)],
    },
    {
        "ref": "O3",
        "customer": "nur_aisyah",
        "pickup_outlet": None,
        "delivery_address": "Blk 456 Bishan Street 13",
        "est_delivery_in_days": 2,
        "status": "CONFIRMED",
        "points_discount_cents": 200,
        "days_ago": 1,
        "items": [
            ("Indoor Cat Dry Food 1.2kg", 2),
            ("Tuna Pâté Wet Food (12 cans)", 1),
        ],
    },
    {
        "ref": "O4",
        "customer": "kumar_r",
        "pickup_outlet": "Pawpal Bishan",
        "delivery_address": None,
        "est_delivery_in_days": None,
        "status": "PENDING",
        "points_discount_cents": 0,
        "days_ago": 0,
        "items": [("Joint Support Supplement (60 tabs)", 1)],
    },
    {
        "ref": "O5",
        "customer": "chloe_ng",
        "pickup_outlet": None,
        "delivery_address": "Blk 789 Woodlands Drive 50",
        "est_delivery_in_days": None,
        "status": "CANCELLED",
        "points_discount_cents": 0,
        "days_ago": 5,
        "items": [("Oatmeal Pet Shampoo 500ml", 1)],
    },
    {
        "ref": "O6",
        "customer": "amy_tan",
        "pickup_outlet": "Pawpal Tampines",
        "delivery_address": None,
        "est_delivery_in_days": None,
        "status": "CONFIRMED",
        "points_discount_cents": 0,
        "days_ago": 0,
        "items": [("Feather Wand Teaser", 1), ("Slicker Brush", 1)],
    },
]

# Mock data – services and bookings

services = [
    {
        "name": "Basic Bath & Brush",
        "category": "GROOMING",
        "duration_minutes": 60,
        "price_cents": 4500,
        "description": "Shampoo, blow-dry, brushing and nail trim.",
    },
    {
        "name": "Full Grooming Package",
        "category": "GROOMING",
        "duration_minutes": 120,
        "price_cents": 8500,
        "description": "Bath, haircut and styling, ear cleaning and nail trim.",
    },
    {
        "name": "Daycare (Full Day)",
        "category": "DAYCARE",
        "duration_minutes": 480,
        "price_cents": 5500,
        "description": "Supervised play, rest and meals from 9am to 5pm.",
    },
    {
        "name": "Overnight Boarding",
        "category": "BOARDING",
        "duration_minutes": None,
        "price_cents": 7000,
        "description": "Price per night. Includes meals and two walks a day.",
    },
    {
        "name": "Puppy Training Session",
        "category": "OTHER",
        "duration_minutes": 60,
        "price_cents": 6000,
        "description": "One-to-one basic obedience session with a trainer.",
    },
]

# day = days from today (negative = past). Boarding slots end the next day at 12:00.
time_slots = [
    {
        "ref": "S1",
        "outlet": "Pawpal Tampines",
        "service": "Basic Bath & Brush",
        "day": -10,
        "start": "10:00",
        "capacity": 3,
    },
    {
        "ref": "S2",
        "outlet": "Pawpal Jurong East",
        "service": "Full Grooming Package",
        "day": -6,
        "start": "14:00",
        "capacity": 2,
    },
    {
        "ref": "S3",
        "outlet": "Pawpal Bishan",
        "service": "Daycare (Full Day)",
        "day": -3,
        "start": "09:00",
        "capacity": 10,
    },
    {
        "ref": "S4",
        "outlet": "Pawpal Tampines",
        "service": "Overnight Boarding",
        "day": -14,
        "start": "14:00",
        "capacity": 5,
    },
    {
        "ref": "S5",
        "outlet": "Pawpal Tampines",
        "service": "Full Grooming Package",
        "day": 2,
        "start": "11:00",
        "capacity": 2,
    },
    {
        "ref": "S6",
        "outlet": "Pawpal Jurong East",
        "service": "Basic Bath & Brush",
        "day": 3,
        "start": "10:00",
        "capacity": 3,
    },
    {
        "ref": "S7",
        "outlet": "Pawpal Bishan",
        "service": "Puppy Training Session",
        "day": 5,
        "start": "16:00",
        "capacity": 4,
    },
    {
        "ref": "S8",
        "outlet": "Pawpal Tampines",
        "service": "Daycare (Full Day)",
        "day": 1,
        "start": "09:00",
        "capacity": 10,
    },
    {
        "ref": "S9",
        "outlet": "Pawpal Tampines",
        "service": "Basic Bath & Brush",
        "day": 7,
        "start": "15:00",
        "capacity": 3,
    },  # empty
    {
        "ref": "S10",
        "outlet": "Pawpal Jurong East",
        "service": "Overnight Boarding",
        "day": 10,
        "start": "14:00",
        "capacity": 5,
    },  # empty
    {
        "ref": "S11",
        "outlet": "Pawpal Bishan",
        "service": "Full Grooming Package",
        "day": 4,
        "start": "10:00",
        "capacity": 1,
    },  # becomes full
]

bookings = [
    {
        "ref": "B1",
        "customer": "amy_tan",
        "pet": "Mochi",
        "slot": "S1",
        "nights": None,
        "status": "COMPLETED",
        "points_discount_cents": 0,
        "days_ago": 14,
    },
    {
        "ref": "B2",
        "customer": "jason_lee",
        "pet": "Bobby",
        "slot": "S2",
        "nights": None,
        "status": "COMPLETED",
        "points_discount_cents": 0,
        "days_ago": 9,
    },
    {
        "ref": "B3",
        "customer": "nur_aisyah",
        "pet": "Kopi",
        "slot": "S3",
        "nights": None,
        "status": "COMPLETED",
        "points_discount_cents": 0,
        "days_ago": 6,
    },
    {
        "ref": "B4",
        "customer": "kumar_r",
        "pet": "Milo",
        "slot": "S4",
        "nights": 3,
        "status": "COMPLETED",
        "points_discount_cents": 0,
        "days_ago": 18,
    },
    {
        "ref": "B5",
        "customer": "amy_tan",
        "pet": "Luna",
        "slot": "S5",
        "nights": None,
        "status": "CONFIRMED",
        "points_discount_cents": 400,
        "days_ago": 2,
    },  # used 400 points
    {
        "ref": "B6",
        "customer": "jason_lee",
        "pet": "Bobby",
        "slot": "S6",
        "nights": None,
        "status": "PENDING",
        "points_discount_cents": 0,
        "days_ago": 0,
    },  # waiting for payment
    {
        "ref": "B7",
        "customer": "chloe_ng",
        "pet": "Coco",
        "slot": "S7",
        "nights": None,
        "status": "CONFIRMED",
        "points_discount_cents": 0,
        "days_ago": 1,
    },
    {
        "ref": "B8",
        "customer": "nur_aisyah",
        "pet": "Snowy",
        "slot": "S8",
        "nights": None,
        "status": "CANCELLED",
        "points_discount_cents": 0,
        "days_ago": 3,
    },  # cancelled, refunded
    {
        "ref": "B9",
        "customer": "chloe_ng",
        "pet": "Coco",
        "slot": "S11",
        "nights": None,
        "status": "CONFIRMED",
        "points_discount_cents": 0,
        "days_ago": 1,
    },  # fills S11 (capacity 1)
    {
        "ref": "B10",
        "customer": "amy_tan",
        "pet": "Mochi",
        "slot": "S8",
        "nights": None,
        "status": "CONFIRMED",
        "points_discount_cents": 0,
        "days_ago": 1,
    },
]

booking_updates = [
    {
        "booking": "B1",
        "staff": "staff_sarah",
        "new_status": "CONFIRMED",
        "note": "Booking confirmed. See you soon!",
    },
    {
        "booking": "B1",
        "staff": "staff_sarah",
        "new_status": "COMPLETED",
        "note": "Mochi was a good boy! Bath and brush done, nails trimmed.",
    },
    {
        "booking": "B2",
        "staff": "staff_mei",
        "new_status": "COMPLETED",
        "note": "Full groom done. Bobby's coat is shiny.",
    },
    {
        "booking": "B3",
        "staff": "staff_daniel",
        "new_status": "COMPLETED",
        "note": "Kopi napped most of the day and ate well.",
    },
    {
        "booking": "B4",
        "staff": "staff_ravi",
        "new_status": "CONFIRMED",
        "note": "Milo checked in for boarding.",
    },
    {
        "booking": "B4",
        "staff": "staff_ravi",
        "new_status": "COMPLETED",
        "note": "Milo checked out. Ate all meals, walked twice daily.",
    },
    {
        "booking": "B5",
        "staff": "staff_sarah",
        "new_status": "CONFIRMED",
        "note": "Slot confirmed for Luna's full groom.",
    },
    {
        "booking": "B8",
        "staff": "staff_sarah",
        "new_status": "CANCELLED",
        "note": "Cancelled by customer more than 24h before. Full refund.",
    },
]

# Mock data – pet sitting

# Map position of each owner's home, used by the sitter "Distance" filter
owner_coordinates = {
    "amy_tan": ("1.353600", "103.945000"),     # Tampines
    "jason_lee": ("1.333100", "103.742400"),   # Jurong East
    "nur_aisyah": ("1.351700", "103.848600"),  # Bishan
    "kumar_r": ("1.311700", "103.795800"),     # Holland Grove
    "chloe_ng": ("1.436900", "103.786000"),    # Woodlands
}

sitting_requests = [
    {
        "ref": "R1",
        "owner": "amy_tan",
        "sitter": "sitter_grace",
        "pets": ["Mochi", "Luna"],
        "start_day": -20,
        "days": 3,
        "status": "completed",
        "care_requirements": "Feed twice a day. Luna is shy, give her space.",
        "owner_rating": 5,
        "owner_feedback": "Grace sent photos every day. Will book again!",
        "days_ago": 25,
    },
    {
        "ref": "R2",
        "owner": "jason_lee",
        "sitter": "sitter_hafiz",
        "pets": ["Bobby"],
        "start_day": 6,
        "days": 2,
        "status": "accepted",
        "care_requirements": "Two long walks daily. Bobby pulls on the leash.",
        "owner_rating": None,
        "owner_feedback": "",
        "days_ago": 3,
    },
    {
        "ref": "R3",
        "owner": "nur_aisyah",
        "sitter": None,
        "pets": ["Kopi", "Snowy"],
        "start_day": 14,
        "days": 4,
        "status": "open",
        "care_requirements": "Snowy needs her coat brushed daily.",
        "owner_rating": None,
        "owner_feedback": "",
        "days_ago": 1,
    },
    {
        "ref": "R4",
        "owner": "chloe_ng",
        "sitter": "sitter_grace",
        "pets": ["Coco"],
        "start_day": 3,
        "days": 1,
        "status": "pending",
        "care_requirements": "Coco gets anxious with loud noises.",
        "owner_rating": None,
        "owner_feedback": "",
        "days_ago": 1,
    },
    {
        "ref": "R5",
        "owner": "kumar_r",
        "sitter": "sitter_hafiz",
        "pets": ["Milo"],
        "start_day": -2,
        "days": 5,
        "status": "in_progress",
        "care_requirements": "Joint supplement with breakfast.",
        "owner_rating": None,
        "owner_feedback": "",
        "days_ago": 7,
    },
    {
        "ref": "R6",
        "owner": "jason_lee",
        "sitter": "sitter_grace",
        "pets": ["Bobby"],
        "start_day": 9,
        "days": 2,
        "status": "declined",
        "care_requirements": "Two walks a day.",
        "owner_rating": None,
        "owner_feedback": "",
        "days_ago": 2,
    },
    {
        "ref": "R7",
        "owner": "amy_tan",
        "sitter": None,
        "pets": ["Mochi"],
        "start_day": 20,
        "days": 4,
        "status": "open",
        "care_requirements": "Morning and evening meals. Daily photo update requested.",
        "owner_rating": None,
        "owner_feedback": "",
        "days_ago": 0,
    },
    {
        "ref": "R8",
        "owner": "jason_lee",
        "sitter": "sitter_grace",
        "pets": ["Bobby"],
        "start_day": 28,
        "days": 3,
        "status": "accepted",
        "care_requirements": "Two walks daily and fresh water.",
        "owner_rating": None,
        "owner_feedback": "",
        "days_ago": 1,
    },
    {
        "ref": "R9",
        "owner": "nur_aisyah",
        "sitter": "sitter_grace",
        "pets": ["Kopi"],
        "start_day": -1,
        "days": 3,
        "status": "in_progress",
        "care_requirements": "Keep the litter box clean and feed at 8am and 7pm.",
        "owner_rating": None,
        "owner_feedback": "",
        "days_ago": 2,
    },
    {
        "ref": "R10",
        "owner": "chloe_ng",
        "sitter": "sitter_grace",
        "pets": ["Coco"],
        "start_day": -18,
        "days": 2,
        "status": "completed",
        "care_requirements": "Coco is nervous around strangers. Give her quiet time.",
        "owner_rating": 5,
        "owner_feedback": "Grace sent clear updates and took great care of Coco.",
        "days_ago": 22,
    },
    {
        "ref": "R11",
        "owner": "kumar_r",
        "sitter": None,
        "pets": ["Milo"],
        "start_day": 35,
        "days": 5,
        "status": "open",
        "care_requirements": "Give joint supplements with breakfast and take short walks.",
        "owner_rating": None,
        "owner_feedback": "",
        "days_ago": 0,
    },
]

sitting_updates = [
    {
        "request": "R1",
        "sitter": "sitter_grace",
        "new_status": "in_progress",
        "note": "Picked up the keys. Mochi and Luna have settled in.",
    },
    {
        "request": "R1",
        "sitter": "sitter_grace",
        "new_status": "completed",
        "note": "All done! Both pets were fed and happy.",
    },
    {
        "request": "R5",
        "sitter": "sitter_hafiz",
        "new_status": "in_progress",
        "note": "Day 1: Milo enjoyed a long walk at the park.",
    },
    {
        "request": "R5",
        "sitter": "sitter_hafiz",
        "new_status": "",
        "note": "Day 2: Ate all his food and took his supplement.",
    },
    {
        "request": "R9",
        "sitter": "sitter_grace",
        "new_status": "in_progress",
        "note": "Kopi settled in well and finished dinner.",
    },
    {
        "request": "R9",
        "sitter": "sitter_grace",
        "new_status": "",
        "note": "Litter box cleaned and morning meal given.",
    },
    {
        "request": "R10",
        "sitter": "sitter_grace",
        "new_status": "completed",
        "note": "Coco was calm and happy at pick-up.",
    },
]

# Mock data – payments, points and reviews

# for = which booking (B), order (O) or sitting request (R) the payment is for
payments = [
    {"for": "B1", "status": "COMPLETED", "days_ago": 14},
    {"for": "B2", "status": "COMPLETED", "days_ago": 9},
    {"for": "B3", "status": "COMPLETED", "days_ago": 6},
    {"for": "B4", "status": "COMPLETED", "days_ago": 18},
    {"for": "B5", "status": "COMPLETED", "days_ago": 2},
    {"for": "B6", "status": "PENDING", "days_ago": 0},
    {"for": "B7", "status": "COMPLETED", "days_ago": 1},
    {"for": "B8", "status": "REFUNDED", "days_ago": 3},
    {"for": "B9", "status": "COMPLETED", "days_ago": 1},
    {"for": "B10", "status": "COMPLETED", "days_ago": 1},
    {"for": "O1", "status": "COMPLETED", "days_ago": 20},
    {"for": "O2", "status": "COMPLETED", "days_ago": 12},
    {"for": "O3", "status": "COMPLETED", "days_ago": 1},
    {"for": "O5", "status": "REFUNDED", "days_ago": 5},
    {"for": "O6", "status": "COMPLETED", "days_ago": 0},
    {"for": "R1", "status": "COMPLETED", "days_ago": 21},
    {"for": "R2", "status": "COMPLETED", "days_ago": 3},
    {"for": "R5", "status": "COMPLETED", "days_ago": 7},
]

# Points rules for the demo: earn 1 point per $1 paid; 100 points = $1 off (1 point = 1 cent).
SIGN_UP_BONUS = 200

reviews = [
    {
        "reviewer": "amy_tan",
        "for": "B1",
        "rating": 5,
        "comment": "Mochi came back smelling amazing!",
    },
    {
        "reviewer": "jason_lee",
        "for": "B2",
        "rating": 4,
        "comment": "Great groom, a short wait at pick-up.",
    },
    {
        "reviewer": "nur_aisyah",
        "for": "B3",
        "rating": 5,
        "comment": "Kopi was relaxed when I picked her up.",
    },
    {
        "reviewer": "kumar_r",
        "for": "B4",
        "rating": 4,
        "comment": "Milo was well cared for. Daily updates were nice.",
    },
    {
        "reviewer": "amy_tan",
        "for": "R1",
        "rating": 5,
        "comment": "Grace was fantastic with both pets.",
    },
]


# Load data view

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
            line1=address["line1"],
            line2=address["line2"],
            postal_code=address["postal_code"],
        )
        new_address.save()

    for pet in pets:
        new_pet = Pet(
            owner_id=Customer.objects.get(username=pet["owner"]),
            name=pet["name"],
            pet_type=pet["pet_type"],
            breed=pet["breed"],
            date_of_birth=pet["date_of_birth"],
            weight_kg=pet["weight_kg"],
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
            image_url="",
            price_cents=product["price_cents"],
            stock_quantity=product["stock_quantity"],
            low_stock_level=product["low_stock_level"],
            is_active=product["is_active"],
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
        )
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

        cancelled_at = (
            days_ago(booking["days_ago"] - 1)
            if booking["status"] == "CANCELLED"
            else None
        )

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

    # Points history
    for customer in Customer.objects.filter(is_verified=True):
        PointsTransaction(
            customer=customer,
            points=SIGN_UP_BONUS,
            transaction_type="EARNED",
            reason="Sign-up bonus",
        ).save()

    for ref, payment in payment_for.items():
        target = created[ref]

        # points used as a discount on this booking/order
        discount = getattr(target, "points_discount_cents", 0)
        if discount:
            PointsTransaction(
                customer=payment.customer,
                points=-discount,
                transaction_type="REDEEMED",
                payment=payment,
                reason=f"Redeemed for {ref}",
            ).save()

        # points earned from completed payments (1 point per $1)
        if payment.status == "COMPLETED" and payment.amount_cents >= 100:
            PointsTransaction(
                customer=payment.customer,
                points=payment.amount_cents // 100,
                transaction_type="EARNED",
                payment=payment,
                reason=f"Earned from {ref}",
            ).save()

    # point_balance = total of each customer's points history
    for customer in Customer.objects.all():
        total = sum(t.points for t in customer.points_transactions.all())
        customer.point_balance = total
        customer.save()

    # Reviews
    for review in reviews:
        target = created[review["for"]]
        new_review = Review(
            reviewer=Customer.objects.get(username=review["reviewer"]),
            booking=target if review["for"].startswith("B") else None,
            sitting_request=target if review["for"].startswith("R") else None,
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


def load_staff_owner_data(request):
    """Create or update only the demo business owner and staff accounts."""
    owner_password = os.getenv("PAWPAL_OWNER_PASSWORD", DEMO_PASSWORD)
    staff_password = os.getenv("PAWPAL_STAFF_PASSWORD", DEMO_PASSWORD)

    outlet = Outlet.objects.filter(is_active=True).first()
    if outlet is None:
        outlet = Outlet.objects.create(
            name="Pawpal Tampines",
            address="10 Tampines Central 1, #01-15",
            postal_code="529536",
            phone="61234501",
            opening_time=outlet_time("09:00"),
            closing_time=outlet_time("21:00"),
            is_active=True,
        )

    owner = BusinessOwner.objects.filter(email="pawpal.sg.demo@gmail.com").first()
    if owner is None:
        owner = BusinessOwner(username="owner_lim")
    owner.email = "pawpal.sg.demo@gmail.com"
    owner.first_name = "Grace"
    owner.last_name = "Tan"
    owner.mobile = "91234567"
    owner.password = make_password(owner_password)
    owner.is_verified = True
    owner.is_active = True
    owner.is_business_owner = True
    owner.save()

    staff = Staff.objects.filter(email="staff_test@pawpal.local").first()
    if staff is None:
        staff = Staff(username="staff_test")
    staff.email = "staff_test@pawpal.local"
    staff.first_name = "Staff"
    staff.last_name = "Test"
    staff.mobile = "90000000"
    staff.password = make_password(staff_password)
    staff.is_verified = True
    staff.is_active = True
    staff.is_staff = True
    staff.outlet = outlet
    staff.save()

    return HttpResponse(
        "Staff and business owner demo accounts loaded successfully. "
        "Existing application data was not changed."
    )


# Business owner pages

PAID_STATUSES = ["CONFIRMED", "COMPLETED"]  # orders that count as revenue

# bookings that count as revenue: confirmed, pet in care (checked in /
# in progress / ready for pick-up) or completed. Not pending or cancelled.
PAID_BOOKING_STATUSES = [
    Booking.Status.CONFIRMED,
    *Booking.IN_CARE_STATUSES,
    Booking.Status.COMPLETED,
]


def money(cents):
    # 4892000 -> "48,920.00"
    return f"{cents / 100:,.2f}"


def percent_change(now, before):
    # e.g. 110 vs 100 -> 10 (%). None when there is nothing to compare with.
    if not before:
        return None
    return round((now - before) * 100 / before)


def revenue_for_period(start_date, end_date, outlet=None):
    """Add up revenue for one date range, split by stream.

    Services and products are linked to an outlet; delivery orders and
    pet sitting are not, so they are left out when one outlet is chosen.
    """
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
    sittings = SittingRequest.objects.filter(
        status=SittingRequest.Status.COMPLETED,
        end_date__gte=start_date,
        end_date__lte=end_date,
    )
    if outlet is not None:
        bookings = bookings.filter(slot__outlet=outlet)
        orders = orders.filter(pickup_outlet=outlet)
        sittings = sittings.none()

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

    # Revenue breakdown table: one row per stream
    breakdown = []
    streams = [
        ("services", "Service bookings"),
        ("products", "Product sales"),
        ("delivery", "Delivery fees"),
        ("commission", "Pet sitting commission (10%)"),
    ]
    for key, label in streams:
        share = round(current[key] * 100 / current["total"]) if current["total"] else 0
        breakdown.append({
            "label": label,
            "amount": money(current[key]),
            "share": share,
            "change": percent_change(current[key], previous[key]),
        })

    # Revenue by outlet
    outlet_rows = []
    for each_outlet in Outlet.objects.filter(is_active=True).order_by("name"):
        outlet_revenue = revenue_for_period(start, end, each_outlet)
        outlet_rows.append({
            "name": each_outlet.name,
            "amount": money(outlet_revenue["total"]),
            "bookings": outlet_revenue["booking_count"],
        })

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
        booking_volume_rows.append({"service": service_name, "outlet": outlet_name, "count": count})
    booking_volume_rows.sort(key=lambda row: row["count"], reverse=True)

    top_services = sorted(service_counts.items(), key=lambda item: item[1], reverse=True)[:3]

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
        product_counts[item.product.name] = product_counts.get(item.product.name, 0) + item.quantity
    top_products = sorted(product_counts.items(), key=lambda item: item[1], reverse=True)[:3]

    # New vs returning customers
    active_customer_ids = set()
    for booking in period_bookings:
        active_customer_ids.add(booking.customer_id)
    for order in Order.objects.filter(created_at__date__gte=start, created_at__date__lte=end):
        active_customer_ids.add(order.customer_id)

    new_customers = 0
    returning_customers = 0
    for customer in Customer.objects.filter(pk__in=active_customer_ids):
        if customer.date_joined.date() >= start:
            new_customers += 1  # joined during this period
        else:
            returning_customers += 1  # joined earlier and came back
    active_total = new_customers + returning_customers
    returning_percent = round(returning_customers * 100 / active_total) if active_total else 0

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
    sitting_jobs = (
        SittingRequest.objects.filter(
            status=SittingRequest.Status.COMPLETED,
            end_date__gte=start,
            end_date__lte=end,
        )
        .select_related("owner", "sitter")
        .order_by("-end_date")
    )
    paid_to_sitters = 0
    for job in sitting_jobs:
        paid_to_sitters += job.sitter_payout_cents

    # Export CSV with the same filters
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="pawpal-report-{start}-to-{end}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Pawpal report", f"{start} to {end}", outlet.name if outlet else "All outlets"])
        writer.writerow([])
        writer.writerow(["Revenue stream", "Revenue (SGD)", "Share (%)", "Change vs previous period (%)"])
        for row in breakdown:
            writer.writerow([row["label"], row["amount"], row["share"], row["change"] if row["change"] is not None else ""])
        total_change = percent_change(current["total"], previous["total"])
        writer.writerow(["Total", money(current["total"]), 100, total_change if total_change is not None else ""])
        writer.writerow([])
        writer.writerow(["Outlet", "Revenue (SGD)", "Bookings"])
        for row in outlet_rows:
            writer.writerow([row["name"], row["amount"], row["bookings"]])
        writer.writerow([])
        writer.writerow(["Service", "Outlet", "Bookings"])
        for row in booking_volume_rows:
            writer.writerow([row["service"], row["outlet"], row["count"]])
        writer.writerow([])
        writer.writerow(["Top product", "Quantity sold"])
        for name, quantity in top_products:
            writer.writerow([name, quantity])
        writer.writerow([])
        writer.writerow(["New customers", new_customers, "Returning customers", returning_customers])
        writer.writerow(["Points issued", points_issued, "Points redeemed", points_redeemed])
        writer.writerow([])
        writer.writerow(["Sitting job end date", "Owner", "Sitter", "Job price", "Commission (10%)", "Paid to sitter"])
        for job in sitting_jobs:
            writer.writerow([job.end_date, job.owner.first_name, job.sitter.first_name, job.total_price_display, job.commission_display, job.sitter_payout_display])
        return response

    # Stacked bar chart: last 6 months
    chart = []
    for months_back in range(5, -1, -1):
        total_months = end.year * 12 + (end.month - 1) - months_back
        month_start = date(total_months // 12, total_months % 12 + 1, 1)
        next_month = date(month_start.year + (month_start.month // 12), month_start.month % 12 + 1, 1)
        month_end = next_month - timedelta(days=1)
        month_revenue = revenue_for_period(month_start, month_end, outlet)
        chart.append({"label": month_start.strftime("%b"), "revenue": month_revenue})

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

    # greeting in Singapore time
    hour = datetime.now(SGT).hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"

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
        "new_customers": new_customers,
        "returning_customers": returning_customers,
        "returning_percent": returning_percent,
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
        selected_id = first_customer.pk if first_customer else None
    selected_customer = (
        Customer.objects.prefetch_related("pets", "addresses")
        .filter(pk=selected_id)
        .first()
        if selected_id
        else None
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
        customer_orders = Order.objects.filter(customer=selected_customer).order_by("-created_at")
        points_history = PointsTransaction.objects.filter(customer=selected_customer).order_by("-created_at")[:8]

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

    reason = request.POST.get("reason", "").strip()
    try:
        points = int(request.POST.get("points", ""))
    except ValueError:
        points = 0

    if points == 0:
        messages.error(request, "Enter a number of points to add (e.g. 200) or deduct (e.g. -200).")
    elif not reason:
        messages.error(request, "A reason is required for every points adjustment.")
    elif customer.point_balance + points < 0:
        messages.error(request, f"Cannot deduct {-points} points. The customer only has {customer.point_balance}.")
    else:
        add_points(customer, points, PointsTransaction.Type.ADJUSTED, reason)
        messages.success(request, f"{points:+d} points saved. New balance: {customer.point_balance}.")

    return redirect(back_to_customer)


def owner_edit_customer(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
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
        },
    )


def owner_review_sitter(request, pk):
    sitter = get_object_or_404(PetSitter, pk=pk)
    if request.method != "POST":
        return_to = request.POST.get("return_to", "/admin-panel/pet-sitters/")
        return redirect(f"{return_to}?sitter={sitter.pk}")

    action = request.POST.get("action")
    owner = get_object_or_404(BusinessOwner, pk=request.session["user_id"])
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
        messages.success(request, "Pet sitter application approved. The applicant has been emailed.")
    elif action == "reject":
        reason = request.POST.get("rejection_reason", "").strip()
        if not reason:
            messages.error(request, "A rejection reason is required.")
        else:
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
            messages.success(request, "Pet sitter application rejected. The applicant has been emailed.")
    else:
        messages.error(request, "Invalid sitter review action.")
    return redirect(f"/admin-panel/pet-sitters/?sitter={sitter.pk}")


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


def owner_toggle_staff(request, pk):
    if request.method != "POST":
        return redirect("core:owner_staff")
    staff = get_object_or_404(Staff, pk=pk)
    staff.is_active = not staff.is_active
    staff.save(update_fields=["is_active"])
    action = "activated" if staff.is_active else "deactivated"
    messages.success(request, f"{staff.first_name or staff.username} was {action}.")
    return redirect("core:owner_staff")


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
            messages.success(request, f"{staff.first_name or staff.username} was updated.")
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
