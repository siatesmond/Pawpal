from django.shortcuts import render

# Create your views here

def product_list(request):
    products = [
        {"name": "Grain-free salmon kibble 2kg", "brand": "test",
         "pet_type": "Dog", "price": 42.90,
         "stock_quantity": 10, "low_stock_level": 5},
        {"name": "Puppy starter kibble 1.5kg", "brand": "test",
         "pet_type": "Dog", "price": 29.90,
         "stock_quantity": 0, "low_stock_level": 5},
        {"name": "Senior joint-care kibble 2kg", "brand": "test",
         "pet_type": "Dog", "price": 45.00,
         "stock_quantity": 3, "low_stock_level": 5},
        {"name": "Grain-free salmon kibble 2kg", "brand": "test",
         "pet_type": "Dog", "price": 42.90,
         "stock_quantity": 10, "low_stock_level": 5},
        {"name": "Puppy starter kibble 1.5kg", "brand": "test",
         "pet_type": "Dog", "price": 29.90,
         "stock_quantity": 0, "low_stock_level": 5},
        {"name": "Senior joint-care kibble 2kg", "brand": "test",
         "pet_type": "Dog", "price": 45.00,
         "stock_quantity": 3, "low_stock_level": 5},
         {"name": "Grain-free salmon kibble 2kg", "brand": "test",
         "pet_type": "Dog", "price": 42.90,
         "stock_quantity": 10, "low_stock_level": 5},
        {"name": "Puppy starter kibble 1.5kg", "brand": "test",
         "pet_type": "Dog", "price": 29.90,
         "stock_quantity": 0, "low_stock_level": 5},
        {"name": "Senior joint-care kibble 2kg", "brand": "test",
         "pet_type": "Dog", "price": 45.00,
         "stock_quantity": 3, "low_stock_level": 5},
    ]
    return render(request, "inventory/product_list.html", {"products": products})