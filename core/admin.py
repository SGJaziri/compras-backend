from django.contrib import admin
from .models import Category, Product, Restaurant, Purchase, PurchaseItem
admin.site.register([Category, Product, Restaurant, Purchase, PurchaseItem])