# core/admin.py
from django.contrib import admin
from .models import (
    Unit, Category, Product, Restaurant,
    Purchase, PurchaseItem,
    PurchaseList, PurchaseListItem
)

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "symbol", "is_currency")
    search_fields = ("name", "symbol")
    list_filter = ("kind", "is_currency")

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)

@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "address", "contact")
    search_fields = ("name", "code")

class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0

@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("serial", "restaurant", "issue_date", "total_amount")
    date_hierarchy = "issue_date"
    inlines = [PurchaseItemInline]

class PurchaseListItemInline(admin.TabularInline):
    model = PurchaseListItem
    extra = 0

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "default_unit", "ref_price")
    search_fields = ("name",)
    list_filter = ("category",)
    filter_horizontal = ("allowed_units",)

@admin.register(PurchaseList)
class PurchaseListAdmin(admin.ModelAdmin):
    list_display = ("series_code", "restaurant", "status", "created_at", "finalized_at")
    list_filter = ("status", "restaurant")
    date_hierarchy = "created_at"
    inlines = [PurchaseListItemInline]

@admin.register(PurchaseListItem)
class PurchaseListItemAdmin(admin.ModelAdmin):
    list_display = ("purchase_list", "product", "unit", "qty", "price_soles")
    list_filter = ("unit", "product__category")
    search_fields = ("product__name",)
