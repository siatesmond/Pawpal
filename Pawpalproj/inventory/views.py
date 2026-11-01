from django.shortcuts import render, HttpResponse

from .models import Brand, Category, Order, Product

categories = ["Food", "Treats", "Toys", "Accessories", "Grooming"]

brands = ["Black Hawk", "Royal Canin", "Buddy Bites", "Health Extension", "Pet Mrkt", "Gnawlers", "Feline Natural", "Buddy Care"]

products = [
    {
        "name": "Pet Mrkt XL Lightweight Pet Cart Trolley Stroller Pram",
        "category": "Accessories",
        "brand": "Pet Mrkt",
        "pet_type": "DOG",
        "description": "Up to 30kg",
        "price_cents": 20900,
        "stock_quantity": 6,
        "image": "PM-XL-Lightweight-Pet-Trolley-Stroller.jpg",
    },
    {
        "name": "Buddy Bites Adult Dog Fresh Lamb Kibbles",
        "category": "Food",
        "brand": "Buddy Bites",
        "pet_type": "DOG",
        "description": "Balanced everyday nutrition for adult dogs, with lamb as the first ingredient.",
        "price_cents": 3280,
        "stock_quantity": 8,
        "image": "BB-Fresh-Lamb-Adult-Dog-Food.webp",
    },
    {
        "name": "Royal Canin Mini Puppy Wet Dog Food",
        "category": "Food",
        "brand": "Royal Canin",
        "pet_type": "DOG",
        "description": "1.5kg. Complete feed for dogs. For small breed puppies (adult weight from 1 to 10 kg)",
        "price_cents": 2990,
        "stock_quantity": 0,
        "image": "RC-Puppy-Mini-Food.png",
    },
    {
        "name": "Feline Natural Chicken Healthy Bites Grain-Free Freeze-Dried Cat Treats",
        "category": "Treats",
        "brand": "Feline Natural",
        "pet_type": "CAT",
        "description": "50g. Chicken Healthy Bites. Treat your cat with the wholesome goodness of Feline Natural Healthy Bites. Delicious, healthy morsels made with all-natural premium ingredients. ",
        "price_cents": 1390,
        "stock_quantity": 15,
        "image": "FN-Chicken-Healthy-Bites-Cats-Treats.png",
    },
    {
        "name": "Pet Mrkt Rough & Tough Crocodile Dog Toy",
        "category": "Toys",
        "brand": "Pet Mrkt",
        "pet_type": "DOG",
        "description": "Durable cotton plush for gentle chewing.",
        "price_cents": 2700,
        "stock_quantity": 8,
        "image": "PM-Rough-and-Tough-Crocodile-Dog-Toy.png",
    },
    {
        "name": "Gnawlers Lallipop Freeze-Dried Chicken & Apple Cat Treats",
        "category": "Treats",
        "brand": "Gnawlers",
        "pet_type": "CAT",
        "description": "Naturally sourced Vitamins and Minerals.",
        "price_cents": 150,
        "stock_quantity": 3,
        "image": "G-Lallipop-Freeze-Dried-Chicken-Apple-Cat-Treats.webp",
    },  
    {
        "name": "Buddy Care Oatmeal pet shampoo 500ml",
        "category": "Grooming",
        "brand": "Buddy Care",
        "pet_type": "DOG",
        "description": "500ml. Shampoo for Dogs With Irritated Skin.",
        "price_cents": 1690,
        "stock_quantity": 4,
        "image": "BC-Oatmeal-Shampoo.png",
    },
]


def loadData(request):
    Order.objects.all().delete()
    Product.objects.all().delete()
    Brand.objects.all().delete()
    Category.objects.all().delete()

    #Load categories
    for category in categories:
        new_category = Category(name=category)
        new_category.save()

    #Load brands
    for brand in brands:
        new_brand = Brand(name=brand)
        new_brand.save()

    #Load products
    for product in products:
        category_instance = Category.objects.get(name=product['category'])
        brand_instance = Brand.objects.get(name=product['brand'])

        new_product = Product(
            name=product['name'],
            category=category_instance,
            brand=brand_instance,
            pet_type=product['pet_type'],
            description=product['description'],
            price_cents=product['price_cents'],
            stock_quantity=product['stock_quantity'],
            image_url=product['image']
        )

        new_product.save()

    return HttpResponse('Data loaded successfully into the database.')