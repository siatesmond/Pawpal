from django.shortcuts import render, HttpResponse

from django.db.models import Q

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

# Load Data

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

#Views

def product_list(request):
    products = (
        Product.objects
        .filter(is_active=True)
        .select_related("brand")
        .order_by("name")
    )

    # Get filter options from query string
    query = request.GET.get("query", "").strip()
    pets = request.GET.getlist("pet")
    prices = request.GET.getlist("price")
    
    # category ids: keep only numeric values to avoid a crash in the filter query
    categories = []
    for c in request.GET.getlist("category"):
        if c.isdigit():
            categories.append(c)

    # brand ids: keep only numeric values to avoid a crash in the filter query with ValueError
    brands = []
    for b in request.GET.getlist("brand"):
        if b.isdigit():
            brands.append(b)
    
    # Filters
    if pets:
        products = products.filter(pet_type__in=pets)

    if categories:
        products = products.filter(category_id__in=categories)

    if brands:
        products = products.filter(brand_id__in=brands)

    # Price ranges 
    price_ranges = {
        "under20": Q(price_cents__lt=2000),
        "20-50": Q(price_cents__gte=2000, price_cents__lte=5000),
        "over50": Q(price_cents__gt=5000),
    }

    if prices:
        price_filter = Q()
        for key in prices:
            if key in price_ranges:
                price_filter = price_filter | price_ranges[key] # OR shows both ticked options
        products = products.filter(price_filter)

    # Search 
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(brand__name__icontains=query)
        )
    
    # Sort
    sort = request.GET.get("sort", "price_asc")
    if sort == "price_desc":
        products = products.order_by("-price_cents", "name") #name breaks ties by name sort, so that equal prices are in same order
    else:
        sort = "price_asc"
        products = products.order_by("price_cents", "name")

    # Build checkbox options
    pet_options = []
    for value, label in Product.PetType.choices:
        pet_options.append({
            "value": value,
            "label": label,
            "checked": value in pets,
        })

    category_options = []
    for category in Category.objects.all():
        category_options.append({
            "value": category.id,
            "label": category.name,
            "checked": str(category.id) in categories,
        })

    brand_options = []
    for brand in Brand.objects.all():
        brand_options.append({
            "value": brand.id,
            "label": brand.name,
            "checked": str(brand.id) in brands,
        })
    
    # print("PET:", pet_options)
    # print("CAT:", category_options)
    # print("BRAND:", brand_options)

    return render(request, "inventory/product_list.html", {
        "products": products,
        "query": query,
        "sort": sort,
        "pet_options": pet_options,
        "category_options": category_options,
        "brand_options": brand_options,
        "selected_prices": prices,
    })