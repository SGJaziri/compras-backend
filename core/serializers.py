# core/serializers.py
from decimal import Decimal
from rest_framework import serializers
from .models import (
    Unit, Category, Product, Restaurant,
    Purchase, PurchaseItem, PurchaseList, PurchaseListItem
)

# --------- Básicos ---------
class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ("id", "name", "kind", "symbol", "is_currency", "created_at")


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "created_at")


class RestaurantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Restaurant
        fields = ("id", "name", "code", "address", "contact", "created_at")


# --------- Productos ---------
class ProductSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    default_unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.all(), allow_null=True, required=False
    )

    category_name = serializers.SerializerMethodField()
    default_unit_name = serializers.SerializerMethodField()  # <-- CAMBIO

    class Meta:
        model = Product
        fields = [
            'id', 'name',
            'category', 'category_name',
            'default_unit', 'default_unit_name',
            'ref_price',
        ]

    def get_category_name(self, obj):
        return getattr(obj.category, 'name', None)

    def get_default_unit_name(self, obj):
        return getattr(obj.default_unit, 'name', None)
# --------- Compras formales (futuro) ---------
class PurchaseItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseItem
        fields = ("id", "product", "quantity", "unit_price", "line_total")

    read_only_fields = ("line_total",)


class PurchaseSerializer(serializers.ModelSerializer):
    items = PurchaseItemSerializer(many=True, read_only=True)

    class Meta:
        model = Purchase
        fields = ("id", "restaurant", "serial", "issue_date", "notes", "total_amount", "items")


# --------- Listas de compras (builder) ---------
class PurchaseListItemSerializer(serializers.ModelSerializer):
    # Validación de la regla: si la unidad es "Soles", qty es el importe y no se pide price_soles
    
    class Meta:
        model = PurchaseListItem
        fields = ("id", "purchase_list", "product", "unit", "qty", "price_soles")

    def validate(self, attrs):
        unit = attrs.get("unit") or getattr(self.instance, "unit", None)
        qty = attrs.get("qty")
        price = attrs.get("price_soles")

        if unit and unit.is_currency:
            # En "Soles": qty es el importe; no debe venir price_soles
            if price not in (None, ""):
                raise serializers.ValidationError(
                    {"price_soles": "No se requiere precio cuando la unidad es 'Soles'."}
                )
        else:
            # En otras unidades: price_soles es obligatorio y > 0
            if price in (None, ""):
                raise serializers.ValidationError(
                    {"price_soles": "Precio en soles es obligatorio para unidades no monetarias."}
                )
            try:
                if Decimal(price) <= 0:
                    raise serializers.ValidationError(
                        {"price_soles": "El precio debe ser mayor que 0."}
                    )
            except Exception:
                raise serializers.ValidationError({"price_soles": "Precio inválido."})

        if qty is None or Decimal(qty) <= 0:
            raise serializers.ValidationError({"qty": "Cantidad/importe debe ser mayor que 0."})

        return attrs


class PurchaseListSerializer(serializers.ModelSerializer):
    items = PurchaseListItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseList
        fields = (
            "id", "restaurant", "series_code", "status",
            "notes", "observation", "created_by", "created_at", "finalized_at",
            "items",
        )
        read_only_fields = ("series_code", "status", "created_by", "created_at", "finalized_at")
