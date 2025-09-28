from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from rest_framework import serializers

from .models import (
    Unit, Category, Product, Restaurant,
    Purchase, PurchaseItem, PurchaseList, PurchaseListItem
)

# ───────────────── Cambio de contraseña ─────────────────
from django.contrib.auth.password_validation import validate_password

class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField()

    def validate_new_password(self, value):
        validate_password(value)
        return value


# ───────────────── Helpers de ámbito por usuario ─────────────────
def _get_request_user(serializer: serializers.Serializer):
    req = serializer.context.get("request") if serializer.context else None
    return getattr(req, "user", None)

def _dec2(val: Decimal) -> Decimal:
    """Redondeo a 2 decimales."""
    return (val or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ───────────────── Básicos ─────────────────
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


# ───────────────── Productos ─────────────────
class ProductSerializer(serializers.ModelSerializer):
    """
    Filtra category y default_unit por owner=request.user.
    """
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.none())
    default_unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.none(), allow_null=True, required=False
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = _get_request_user(self)
        if user and user.is_authenticated:
            self.fields["category"].queryset = Category.objects.filter(owner=user)
            self.fields["default_unit"].queryset = Unit.objects.filter(owner=user)
        else:
            # Sin usuario autenticado, no permitimos escritura
            self.fields["category"].queryset = Category.objects.none()
            self.fields["default_unit"].queryset = Unit.objects.none()

    def get_category_name(self, obj):
        return getattr(obj.category, "name", None)

    def get_default_unit_name(self, obj):
        return getattr(obj.default_unit, "name", None)

    def validate(self, attrs):
        """
        Asegura que la category y la default_unit pertenezcan al mismo owner (request.user).
        """
        user = _get_request_user(self)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("No autenticado.")

        cat = attrs.get("category") or getattr(self.instance, "category", None)
        du  = attrs.get("default_unit") or getattr(self.instance, "default_unit", None)

        if cat and getattr(cat, "owner_id", None) != user.id:
            raise serializers.ValidationError({"category": "No pertenece al usuario."})
        if du and getattr(du, "owner_id", None) != user.id:
            raise serializers.ValidationError({"default_unit": "No pertenece al usuario."})
        return attrs


# ───────────────── Compras formales (futuro) ─────────────────
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


# ───────────────── Listas de compras (builder) ─────────────────
class PurchaseListItemSerializer(serializers.ModelSerializer):
    """
    Reglas V2:
    - product y unit deben pertenecer al usuario.
    - purchase_list se toma de la URL (read_only) y la inyecta la vista.
    - Si unit.is_currency=True: qty es importe y price_soles se fuerza a None.
    - Si NO es monetaria: en borrador price_soles puede ser None, en final es requerido.
    """
    # Campos de ayuda para el frontend (solo lectura)
    product_name = serializers.SerializerMethodField(read_only=True)
    unit_name = serializers.SerializerMethodField(read_only=True)
    unit_is_currency = serializers.SerializerMethodField(read_only=True)
    subtotal_soles = serializers.SerializerMethodField(read_only=True)

    unit_symbol = serializers.SerializerMethodField(read_only=True)
    restaurant = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PurchaseListItem
        fields = (
            'id', 'restaurant', 'status', 'series_code',
            'created_at', 'finalized_at', 'notes',
            "purchase_list",
            "product", "product_name",
            "unit", "unit_name", "unit_is_currency","unit_symbol",
            "qty",
            "price_soles",
            "subtotal_soles",
        )
        read_only_fields = ("purchase_list",'created_at', 'finalized_at', 'series_code')  # <- **clave**
        extra_kwargs = {
            "price_soles": {"required": False, "allow_null": True},
        }

    def validate_status(self, v):
        # opcional: impedir volver de 'final' a 'draft'
        if self.instance and getattr(self.instance, 'status', '') == 'final' and v != 'final':
            raise serializers.ValidationError("Una lista finalizada no puede volver a borrador.")
        return v

    # Limitar querysets en escritura según el usuario
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Esto ya lo tenías: ajustar queryset en campos de escritura
        if "product" in self.fields:
            from .models import Product
            self.fields["product"].queryset = Product.objects.none()

    # ------- Getters de solo lectura -------
    def get_product_name(self, obj):
        return getattr(obj.product, "name", None)

    def get_unit_name(self, obj):
        return getattr(obj.unit, "name", None)

    def get_unit_symbol(self, obj):
        return getattr(obj.unit, "symbol", None)

    def get_unit_is_currency(self, obj):
        return bool(getattr(obj.unit, "is_currency", False))

    def get_subtotal_soles(self, obj):
        if obj.price_soles is None or obj.qty is None:
            return None
        try:
            return float(obj.price_soles) * float(obj.qty)
        except Exception:
            return None

    def get_restaurant(self, obj):
        return getattr(getattr(obj, "purchase_list", None), "restaurant_id", None)

    # ------- Validación V2 -------
    def validate(self, attrs):
        from .models import Unit as UnitModel, PurchaseList as PurchaseListModel, Product as ProductModel

        user = _get_request_user(self)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("No autenticado.")

        # purchase_list llega por contexto o por la instancia (nunca por attrs porque es read_only)
        pl = (
            attrs.get("purchase_list")
            or getattr(self.instance, "purchase_list", None)
            or (self.context.get("purchase_list") if self.context else None)
        )

        unit = attrs.get("unit") or getattr(self.instance, "unit", None)
        product = attrs.get("product") or getattr(self.instance, "product", None)
        qty  = attrs.get("qty") if "qty" in attrs else getattr(self.instance, "qty", None)
        price = attrs.get("price_soles") if "price_soles" in attrs else getattr(self.instance, "price_soles", None)

        # Existencia y tipos
        if not isinstance(unit, UnitModel):
            raise serializers.ValidationError({"unit": "Unidad inválida."})
        if not isinstance(product, ProductModel):
            raise serializers.ValidationError({"product": "Producto inválido."})
        if pl is None or not isinstance(pl, PurchaseListModel):
            raise serializers.ValidationError({"purchase_list": "Lista inválida o ausente."})
        if qty is None:
            raise serializers.ValidationError({"qty": "Cantidad requerida."})

        # Pertenencia al usuario
        if getattr(unit, "owner_id", None) != user.id:
            raise serializers.ValidationError({"unit": "No pertenece al usuario."})
        if getattr(product, "owner_id", None) != user.id:
            raise serializers.ValidationError({"product": "No pertenece al usuario."})
        if getattr(pl, "created_by_id", None) != user.id:
            raise serializers.ValidationError({"purchase_list": "No pertenece al usuario."})

        # Estado de la lista
        if pl.status == "final":
            raise serializers.ValidationError({"purchase_list": "No se pueden modificar listas finalizadas."})

        # Reglas de precio/importe
        if unit.is_currency:
            # qty = importe; normalizamos price_soles a None
            attrs["price_soles"] = None
        else:
            if qty < 0:
                raise serializers.ValidationError({"qty": "Debe ser mayor o igual a cero."})
            if price is not None:
                try:
                    Decimal(str(price))
                except Exception:
                    raise serializers.ValidationError({"price_soles": "Formato inválido."})
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
        # Evitar que el cliente pueda asignar created_by manualmente
        read_only_fields = ("series_code", "status", "created_by", "created_at", "finalized_at")
