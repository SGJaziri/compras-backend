from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
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

def _to_decimal_or_zero(v):
    if v is None or v == '':
        return Decimal('0')
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


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
        model = PurchaseListItem
        fields = ['price', 'quantity']            # <- sólo lo que edita el modal
        extra_kwargs = {
            'price': {'required': False, 'allow_null': True},
            'quantity': {'required': False},
        }

class PurchaseListItemPatchSerializer(serializers.ModelSerializer):
    """
    PATCH del Historial:
    - Acepta 'price' (o 'price_soles') y lo mapea a price_soles del modelo.
    - Acepta 'quantity' (o 'qty') y lo mapea a qty del modelo.
    - Acepta 'notes' u 'observations' si existen en el modelo.
    """
    # Campos de entrada que puede mandar el front
    price = serializers.CharField(required=False, allow_null=True, write_only=True)
    quantity = serializers.CharField(required=False, write_only=True)
    # aliases opcionales:
    notes = serializers.CharField(required=False, allow_blank=True, write_only=True)
    observations = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = PurchaseListItem
        fields = ['price', 'quantity', 'notes', 'observations']  # solo entrada

    # 🔁 Mapea sinónimos del payload -> campos esperados por este serializer
    def to_internal_value(self, data):
        d = dict(data)
        if 'price' not in d and 'price_soles' in d:
            d['price'] = d.get('price_soles')
        if 'quantity' not in d and 'qty' in d:
            d['quantity'] = d.get('qty')
        if 'notes' not in d and 'observations' in d:
            d['notes'] = d.get('observations')

        # Limpiamos a lo permitido para evitar ruido
        allowed = {'price', 'quantity', 'notes'}
        cleaned = {k: d.get(k) for k in allowed if k in d}
        return super().to_internal_value(cleaned)

    def validate_price(self, value):
        return _to_decimal_or_zero(value)

    def validate_quantity(self, value):
        return _to_decimal_or_zero(value)

    def update(self, instance, validated_data):
        touched = []

        # ↔️ Mapear a los nombres REALES del modelo
        if 'price' in validated_data:
            instance.price_soles = validated_data['price']
            touched.append('price_soles')

        if 'quantity' in validated_data:
            instance.qty = validated_data['quantity']
            touched.append('qty')

        # notas / observaciones (si existen en el modelo)
        text = validated_data.get('notes', None)
        if text is not None:
            if hasattr(instance, 'notes'):
                instance.notes = text
                touched.append('notes')
            elif hasattr(instance, 'observations'):
                instance.observations = text
                touched.append('observations')

        if touched:
            instance.save(update_fields=touched)
        return instance

# ───────────────── Listas de compras (builder) ─────────────────
class PurchaseListItemPatchSerializer(serializers.ModelSerializer):
    """
    PATCH del Historial:
    - Acepta 'price' (o 'price_soles') y lo mapea a price_soles (cuando la unidad NO es monetaria).
      Si la unidad ES monetaria, se fuerza price_soles = None (el importe va en qty).
    - Acepta 'quantity' (o 'qty') y lo mapea a qty.
    - Acepta 'notes' u 'observations' si existen en el modelo.
    """
    # Campos que puede mandar el front (solo entrada)
    price = serializers.CharField(required=False, allow_null=True, write_only=True)
    quantity = serializers.CharField(required=False, allow_null=True, write_only=True)
    notes = serializers.CharField(required=False, allow_blank=True, write_only=True)
    observations = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = PurchaseListItem
        # Solo entrada: devolvemos 200 con un cuerpo mínimo; el frontend hace luego un GET de refresco
        fields = ['price', 'quantity', 'notes', 'observations']

    # ── Normaliza alias del payload → claves esperadas por este serializer
    def to_internal_value(self, data):
        d = dict(data)
        if 'price' not in d and 'price_soles' in d:
            d['price'] = d.get('price_soles')
        if 'quantity' not in d and 'qty' in d:
            d['quantity'] = d.get('qty')
        if 'notes' not in d and 'observations' in d:
            d['notes'] = d.get('observations')

        allowed = {'price', 'quantity', 'notes', 'observations'}
        cleaned = {k: d.get(k) for k in allowed if k in d}
        return super().to_internal_value(cleaned)

    # ── Validaciones/parseo números: deja None si viene null/''; si viene número, a Decimal
    def validate_price(self, value):
        if value in (None, ''):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise serializers.ValidationError("Formato de precio inválido.")

    def validate_quantity(self, value):
        if value in (None, ''):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise serializers.ValidationError("Formato de cantidad inválido.")

    def update(self, instance, validated_data):
        touched = []
        is_currency = bool(getattr(instance.unit, 'is_currency', False))

        # quantity → qty
        if 'quantity' in validated_data and validated_data['quantity'] is not None:
            instance.qty = validated_data['quantity']
            touched.append('qty')

        # price → price_soles (solo si NO es monetaria); si es monetaria, se fuerza a None siempre
        if is_currency:
            # importe va en qty; el precio unitario se borra
            if getattr(instance, 'price_soles', None) is not None:
                instance.price_soles = None
                touched.append('price_soles')
        else:
            if 'price' in validated_data:
                # Puede venir None para “limpiar” el precio en borrador
                instance.price_soles = validated_data['price']
                touched.append('price_soles')

        # notas / observaciones (si el modelo las tuviera)
        text = validated_data.get('notes', None)
        if text is not None:
            if hasattr(instance, 'notes'):
                instance.notes = text
                touched.append('notes')
            elif hasattr(instance, 'observations'):
                instance.observations = text
                touched.append('observations')

        if touched:
            instance.save(update_fields=touched)
        return instance

class PurchaseListItemSerializer(serializers.ModelSerializer):
    """
    Para listar/crear/editar ítems de la lista desde el builder.
    Campos de solo lectura para el front.
    """
    product_name = serializers.SerializerMethodField(read_only=True)
    unit_name = serializers.SerializerMethodField(read_only=True)
    unit_is_currency = serializers.SerializerMethodField(read_only=True)
    unit_symbol = serializers.SerializerMethodField(read_only=True)
    subtotal_soles = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PurchaseListItem
        fields = (
            "id",
            "purchase_list",
            "product", "product_name",
            "unit", "unit_name", "unit_is_currency", "unit_symbol",
            "qty",
            "price_soles",
            "subtotal_soles",
        )
        read_only_fields = ("purchase_list",)
        extra_kwargs = {"price_soles": {"required": False, "allow_null": True}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = _get_request_user(self)
        if user and user.is_authenticated:
            self.fields["product"].queryset = Product.objects.filter(owner=user)
            self.fields["unit"].queryset = Unit.objects.filter(owner=user)
        else:
            self.fields["product"].queryset = Product.objects.none()
            self.fields["unit"].queryset = Unit.objects.none()

    def get_product_name(self, obj): return getattr(obj.product, "name", None)
    def get_unit_name(self, obj):    return getattr(obj.unit, "name", None)
    def get_unit_symbol(self, obj):  return getattr(obj.unit, "symbol", None)
    def get_unit_is_currency(self, obj): return bool(getattr(obj.unit, "is_currency", False))

    def get_subtotal_soles(self, obj):
        try:
            is_currency = bool(getattr(obj.unit, "is_currency", False))
            q = obj.qty or Decimal("0")
            if is_currency:
                return _dec2(q)
            p = obj.price_soles or Decimal("0")
            return _dec2(q * p)
        except Exception:
            return Decimal("0.00")

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
