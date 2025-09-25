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
        fields = ("id", "purchase_list", "product", "unit", "qty", "price_soles", "created_at")
        extra_kwargs = {
            "price_soles": {"required": False, "allow_null": True},  # ✅ clave V2
        }

    def validate(self, attrs):
        # Obtenemos unidad y lista para aplicar reglas coherentes
        unit = attrs.get("unit") or getattr(self.instance, "unit", None)
        pl   = attrs.get("purchase_list") or getattr(self.instance, "purchase_list", None)
        qty  = attrs.get("qty") if "qty" in attrs else getattr(self.instance, "qty", None)
        price = attrs.get("price_soles") if "price_soles" in attrs else getattr(self.instance, "price_soles", None)

        if not unit or not isinstance(unit, Unit):
            raise serializers.ValidationError({"unit": "Unidad inválida."})
        if not pl or not isinstance(pl, PurchaseList):
            raise serializers.ValidationError({"purchase_list": "Lista inválida."})
        if qty is None:
            raise serializers.ValidationError({"qty": "Cantidad requerida."})

        # Reglas V2:
        # - Si la unidad es monetaria: no se usa price_soles (qty ya es el importe)
        # - Si la unidad NO es monetaria:
        #     * en 'draft' se permite price_soles = null
        #     * en 'final' se exige price_soles
        if unit.is_currency:
            # Normalizamos a None para evitar conflictos con clean()
            attrs["price_soles"] = None
        else:
            if pl.status == "final" and price is None:
                raise serializers.ValidationError({"price_soles": "Requerido al finalizar la lista (unidad no monetaria)."})

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
