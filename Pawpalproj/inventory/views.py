from django.shortcuts import render, HttpResponse, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone

from django.db.models import Q, F, Count
from django.db.models import Prefetch

from django.core.paginator import Paginator

from service.models import Booking, BookingUpdate, BookingUpdatePhoto

from user.models import Outlet, Staff, Customer

from .models import Brand, Category, Order, Product, CartItem

from .forms import BookingUpdateForm, StockForm, ProductForm

categories = ["Food", "Treats", "Toys", "Accessories", "Grooming"]

brands = [
    "Black Hawk",
    "Royal Canin",
    "Buddy Bites",
    "Health Extension",
    "Pet Mrkt",
    "Gnawlers",
    "Feline Natural",
    "Buddy Care",
]

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

    # Load categories
    for category in categories:
        new_category = Category(name=category)
        new_category.save()

    # Load brands
    for brand in brands:
        new_brand = Brand(name=brand)
        new_brand.save()

    # Load products
    for product in products:
        category_instance = Category.objects.get(name=product["category"])
        brand_instance = Brand.objects.get(name=product["brand"])

        new_product = Product(
            name=product["name"],
            category=category_instance,
            brand=brand_instance,
            pet_type=product["pet_type"],
            description=product["description"],
            price_cents=product["price_cents"],
            stock_quantity=product["stock_quantity"],
            image_url=product["image"],
        )

        new_product.save()

    return HttpResponse("Data loaded successfully into the database.")


# Views

def bookings(request):
    # Optimize query with select_related for customer, pet, slot, and outlet
    bookings = Booking.objects.select_related(
        "customer", "pet", "slot", "slot__outlet"
    ).order_by("slot__start_time")
    
    outlets = Outlet.objects.all()

    # Read query parameters
    status_filter = request.GET.get("status", "").strip()
    search_query = request.GET.get("query", "").strip()
    outlet_filter = request.GET.get("outlet", "").strip()
    date_filter = request.GET.get("date", "").strip()

    # Filter by status
    if status_filter in Booking.Status.values:
        bookings = bookings.filter(status=status_filter)

    # Filter by outlet
    if outlet_filter.isdigit():
        bookings = bookings.filter(slot__outlet_id=outlet_filter)

    # Filter by date
    if date_filter:
        bookings = bookings.filter(slot__start_time__date=date_filter)

    # Search by customer name or pet name
    if search_query:
        bookings = bookings.filter(
            Q(customer__first_name__icontains=search_query) |
            Q(customer__last_name__icontains=search_query) |
            Q(customer__username__icontains=search_query) |
            Q(pet__name__icontains=search_query)
        )

    # Booking details
    selected_id = request.GET.get("booking", "")
    if not selected_id.isdigit():
        first_booking = bookings.first() #show first booking if no booking is selected
        selected_id = first_booking.pk if first_booking else None

    selected_booking = None
    if selected_id:
        selected_booking = (
            Booking.objects.select_related("customer", "pet", "slot", "slot__service")
            .prefetch_related( # use prefetch_related due to high number of related BookingUpdate objects and BookingUpdatePhoto objects
                Prefetch(
                    "updates",
                    # Fetches all booking updates, pre-loading their photos
                    queryset=BookingUpdate.objects.prefetch_related("photos").order_by("-created_at"),
                    to_attr="ordered_updates",
                ),
            )
            .filter(pk=selected_id)
            .first()
        )

    return render(
        request,
        "inventory/staff_bookings.html",
        {
            "active_page": "bookings",
            "bookings": bookings,
            "outlets": outlets,
            "selected_booking": selected_booking,
            "status_filter": status_filter,
            "search_query": search_query,
            "outlet_filter": outlet_filter,
            "date_filter": date_filter,
            "status_choices": Booking.Status.choices,
        },
    )


# Update Booking
def update_booking(request, pk=None):
    booking = get_object_or_404(
        Booking.objects.select_related("customer", "pet", "slot", "slot__service"),
        pk=pk,
    )
    if request.method == "POST":
        form = BookingUpdateForm(request.POST, request.FILES)
        if form.is_valid():
            booking_update = form.save(commit=False)
            booking_update.booking = booking

            # Get staff id from session and assign to booking_update.staff if user is staff
            if request.session.get("user_type") == "staff":
                booking_update.staff = get_object_or_404(
                    Staff, pk=request.session.get("user_id")
                )

            booking_update.save()

            # Loop through all uploaded files and create individual photo records
            for photo in request.FILES.getlist("photos"):
                BookingUpdatePhoto.objects.create(
                    update=booking_update,
                    photo=photo,
                )

            # Update booking new status from the form input
            booking.status = booking_update.new_status

            if booking.status == Booking.Status.CANCELLED:
                if not booking.cancelled_at:
                    booking.cancelled_at = timezone.now()
            else:
                booking.cancelled_at = None # Clear cancellation metadata if status changes back
                booking.cancellation_fee_cents = 0

            booking.save()

            messages.success(request, f"Booking #{booking.pk} updated successfully.")
            return redirect("inventory:staff_bookings")
    else:
        # Pre-fill the form dropdown with the booking's current status as default 
        form = BookingUpdateForm(initial={"new_status": booking.status})

    return render(
        request,
        "inventory/staff_update_booking.html",
        {
            "form": form,
            "booking": booking,
            "action_title": f"Update Booking #{booking.pk}",
            "cancel_url": "/inventory/staff/bookings/",
        },
    )


def product_list(request):
    products = (
        Product.objects.filter(is_active=True).select_related("brand").order_by("name")
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
                price_filter = (
                    price_filter | price_ranges[key]
                )  # OR shows both ticked options
        products = products.filter(price_filter)

    # Search
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(brand__name__icontains=query)
        )

    # Sort
    sort = request.GET.get("sort", "price_asc")
    if sort == "price_desc":
        products = products.order_by(
            "-price_cents", "name"
        )  # name breaks ties by name sort, so that equal prices are in same order
    else:
        sort = "price_asc"
        products = products.order_by("price_cents", "name")

    # Build checkbox options
    pet_options = []
    for value, label in Product.PetType.choices:
        pet_options.append(
            {
                "value": value,
                "label": label,
                "checked": value in pets,
            }
        )

    category_options = []
    for category in Category.objects.all():
        category_options.append(
            {
                "value": category.id,
                "label": category.name,
                "checked": str(category.id) in categories,
            }
        )

    brand_options = []
    for brand in Brand.objects.all():
        brand_options.append(
            {
                "value": brand.id,
                "label": brand.name,
                "checked": str(brand.id) in brands,
            }
        )

    # print("PET:", pet_options)
    # print("CAT:", category_options)
    # print("BRAND:", brand_options)

    # Pagination
    paginator = Paginator(products, 6)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "inventory/product_list.html",
        {
            "page_obj": page_obj,
            "products": products,
            "query": query,
            "sort": sort,
            "pet_options": pet_options,
            "category_options": category_options,
            "brand_options": brand_options,
            "selected_prices": prices,
        },
    )


def product_detail(request, product_id):
    product = get_object_or_404(
        Product.objects.select_related("brand", "category"),
        pk=product_id,
        is_active=True,
    )

    return render(
        request,
        "inventory/product_detail.html",
        {
            "product": product,
        },
    )


# Orders and Stock (Staff)
def staff_orders_stock(request):

    # Read the options from the query string
    method = request.GET.get("method", "all")
    status = request.GET.get("status", "")
    query = request.GET.get("query", "").strip()

    all_orders = Order.objects.select_related("customer", "pickup_outlet").annotate(
        item_count=Count("items")
    )
    orders = all_orders.order_by("-created_at")

    # pick-up vs delivery
    if method == "pickup":
        orders = orders.filter(
            pickup_outlet__isnull=False
        )  # filter out with no pickup outlet
    elif method == "delivery":
        orders = orders.filter(
            pickup_outlet__isnull=True
        )  # filter out with pickup outlets
    else:
        method = "all"

    # status dropdown list
    if status in Order.Status.values:
        orders = orders.filter(status=status)
    else:
        status = ""

    # search by order number
    if query.isdigit():
        orders = orders.filter(pk=query)

    # tab counts
    counts = { 
        "all": all_orders.count(),
        "pickup": all_orders.filter(pickup_outlet__isnull=False).count(),
        "delivery": all_orders.filter(pickup_outlet__isnull=True).count(),
    }

    # the order shown in the detail panel 
    selected_id = request.GET.get("order", "")
    if not selected_id.isdigit():
        first = orders.first() #show first order if no order is selected
        selected_id = first.pk if first else None

    selected = None
    if selected_id:
        selected = (
            Order.objects.select_related("customer", "delivery_address")
            .prefetch_related("items__product")
            .filter(pk=selected_id)
            .first()
        )

    # stock panel: lowest stock first
    low_count = Product.objects.filter(stock_quantity__lte=F("low_stock_level")).count()
    stock_products = Product.objects.order_by("stock_quantity")

    return render(
        request,
        (
            "core/owner_orders_stock.html"
            if request.session.get("user_type") == "owner"
            else "inventory/staff_orders_stock.html"
        ),
        {
            "active_page": "orders",
            "orders": orders,
            "selected": selected,
            "method": method,
            "status": status,
            "query": query,
            "counts": counts,
            "status_choices": Order.Status.choices,
            "low_count": low_count,
            "stock_products": stock_products,
        },
    )

# Update a specific product's stock quantity 
def update_stock(request, pk):

    product = get_object_or_404(Product, pk=pk)
    action_title = f"Update Stock for Product ID #{product.pk}"

    error_message = None

    if request.method == "POST":
        form = StockForm(request.POST, instance=product)

        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"Stock quantity for Product ID #{product.id}, '{product.name}' "
                "updated successfully.",
            )
            return redirect("inventory:staff_orders_stock")
        else:
            error_message = 'Please correct the errors below.'
    else:
        form = StockForm(instance=product)

    return render(
        request,
        (
            "core/owner_update_stock.html"
            if request.session.get("user_type") == "owner"
            else "inventory/staff_update_stock.html"
        ),
        {
            "form": form, 
            "product": product, 
            "action_title": action_title,
            "error_message": error_message
        }
    )

# Fetch all products
def staff_products(request):
   
    products = Product.objects.select_related("category", "brand").order_by("-id")

    # Read filter options from query string
    query = request.GET.get("query", "").strip()
    category_id = request.GET.get("category", "")
    brand_id = request.GET.get("brand", "")
    pet_type = request.GET.get("pet_type", "")

    # Search by product name
    if query:
        products = products.filter(
            Q(name__icontains=query)
        )

    # Filter by category
    if category_id.isdigit():
        products = products.filter(category_id=category_id)

    # Filter by brand
    if brand_id.isdigit():
        products = products.filter(brand_id=brand_id)

    # Filter by Pet type
    if pet_type in Product.PetType.values:
        products = products.filter(pet_type=pet_type)

    # Product details
    # Filter by product ID
    selected_id = request.GET.get("product", "")
    if not selected_id.isdigit():
        first_product = products.first() #show first product if no product is selected
        selected_id = first_product.pk if first_product else None

    selected_product = None
    if selected_id:
        selected_product = (
            Product.objects.select_related("category", "brand")
            .filter(pk=selected_id)
            .first()
        )

    # Metadata choices for dropdowns
    categories = Category.objects.all()
    brands = Brand.objects.all()
    pet_choices = Product.PetType.choices

    return render(
        request,
        (
            "core/owner_products_catalog.html"
            if request.session.get("user_type") == "owner"
            else "inventory/staff_products.html"
        ),
        {
            "active_page": "products",
            "products": products,
            "selected_product": selected_product,
            "query": query,
            "category_id": category_id,
            "brand_id": brand_id,
            "pet_type": pet_type,
            "categories": categories,
            "brands": brands,
            "pet_choices": pet_choices,
        },
    )

# Add/Update product
def product_form(request, pk=None):
  
    error_message = None

    if pk:
        # Update product
        product = get_object_or_404(Product, pk=pk)
        action_title = f"Update Product ID #{product.pk}"
    else:
        # Add new product
        product = None
        action_title = "Add New Product"

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            saved_product = form.save()
            
            if pk:
                message = (
                    f"Product ID #{saved_product.pk}, "
                    f"'{saved_product.name}' updated successfully."
                )
            else:
                message = f"Product ID #{saved_product.pk}, '{saved_product.name}' created successfully."
            messages.success(request, message)
            return redirect("inventory:staff_products")
        else:
            error_message = "Please correct the errors below."
    else:
        form = ProductForm(instance=product)

    return render(
        request,
        (
            "core/owner_product_form.html"
            if request.session.get("user_type") == "owner"
            else "inventory/staff_product_form.html"
        ),
        {
            "form": form,
            "product": product,
            "action_title": action_title,
            "error_message": error_message,
        },
    )
