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

    category_name = serializers.SerializerMethodField(read_only=True)
    default_unit_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "name",
            "category", "category_name",
            "default_unit", "default_unit_name",
            "ref_price",
        ]

    def get_category_name(self, obj):
        return getattr(obj.category, "name", None)

    def get_default_unit_name(self, obj):
        return getattr(obj.default_unit, "name", None)


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
    # Campos de ayuda para el frontend (solo lectura)
    product_name = serializers.SerializerMethodField(read_only=True)
    unit_name = serializers.SerializerMethodField(read_only=True)
    unit_is_currency = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PurchaseListItem
        fields = (
            "id",
            "purchase_list",
            "product", "product_name",
            "unit", "unit_name", "unit_is_currency",
            "qty",
            "price_soles",
        )
        extra_kwargs = {
            # V2: precio no es requerido en borrador; permitimos null
            "price_soles": {"required": False, "allow_null": True},
        }

    # ------- Getters de solo lectura -------
    def get_product_name(self, obj):
        return getattr(obj.product, "name", None)

    def get_unit_name(self, obj):
        return getattr(obj.unit, "name", None)

    def get_unit_is_currency(self, obj):
        return bool(getattr(obj.unit, "is_currency", False))

    # ------- Validación V2 -------
    def validate(self, attrs):
        """
        Reglas:
        - Si la unidad es monetaria (is_currency=True): qty es el importe, price_soles no aplica (forzamos None).
        - Si la unidad NO es monetaria:
            * En 'draft' permitimos price_soles = None.
            * En 'final' price_soles es obligatorio.
        """
        # Import local para evitar dependencias circulares en algunos entornos
        from .models import Unit as UnitModel, PurchaseList as PurchaseListModel

        unit = attrs.get("unit") or getattr(self.instance, "unit", None)
        pl   = attrs.get("purchase_list") or getattr(self.instance, "purchase_list", None)
        qty  = attrs.get("qty") if "qty" in attrs else getattr(self.instance, "qty", None)
        price = attrs.get("price_soles") if "price_soles" in attrs else getattr(self.instance, "price_soles", None)

        if not unit or not isinstance(unit, UnitModel):
            raise serializers.ValidationError({"unit": "Unidad inválida."})
        if not pl or not isinstance(pl, PurchaseListModel):
            raise serializers.ValidationError({"purchase_list": "Lista inválida."})
        if qty is None:
            raise serializers.ValidationError({"qty": "Cantidad requerida."})

        if unit.is_currency:
            # qty = importe; normalizamos price_soles a None
            attrs["price_soles"] = None
        else:
            if pl.status == "final" and price is None:
                raise serializers.ValidationError({
                    "price_soles": "Requerido al finalizar la lista (unidad no monetaria)."
                })

        return attrs


class PurchaseListSerializer(serializers.ModelSerializer):
    items = PurchaseListItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseList
        fields = (
            "id",
            "restaurant",
            "series_code",
            "status",
            "notes",
            "observation",
            "created_by",
            "created_at",
            "finalized_at",
            "items",
        )
        read_only_fields = ("series_code", "status", "created_by", "created_at", "finalized_at")
