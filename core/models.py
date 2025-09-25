# core/models.py
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

# -----------------------------------
# Catálogo de Unidades
# -----------------------------------
class Unit(models.Model):
    KIND_CHOICES = (
        ("mass", "Mass"),
        ("count", "Count"),
        ("currency", "Currency"),
        ("package", "Package"),
        ("other", "Other"),
    )

    # Ej.: 'Kilogramo', 'Unidad', 'Soles'
    name = models.CharField(max_length=40, unique=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="other")
    # Ej.: 'kg', 'uni', 'S/'
    symbol = models.CharField(max_length=10, blank=True, null=True)
    # Si es True, la cantidad (qty) representa un importe en S/
    is_currency = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


# -----------------------------------
# Catálogo
# -----------------------------------
class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Restaurant(models.Model):
    name = models.CharField(max_length=120, unique=True)
    address = models.CharField(max_length=200, blank=True, null=True)
    contact = models.CharField(max_length=120, blank=True, null=True)
    # Código corto, ej.: 'ALP', 'MIL'
    code = models.CharField(max_length=3, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        # Normalizamos a 3 letras mayúsculas
        if self.code:
            self.code = self.code.upper()[:3]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Product(models.Model):
    name = models.CharField(max_length=120)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    ref_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    default_unit = models.ForeignKey(
        Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Menú de unidades permitidas para este producto (opcional)
    allowed_units = models.ManyToManyField(Unit, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "category"], name="uniq_product_name_per_category"
            ),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} / {self.category.name}"


# -----------------------------------
# Compras formales (opcional para futuras extensiones)
# -----------------------------------
class Purchase(models.Model):
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.PROTECT, related_name="purchases"
    )
    serial = models.CharField(max_length=32, unique=True)
    issue_date = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    class Meta:
        ordering = ["-issue_date"]

    def __str__(self) -> str:
        return f"{self.serial} - {self.restaurant.name}"


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    line_total = models.DecimalField(max_digits=12, decimal_places=2, editable=False)

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or Decimal("0")) * (self.unit_price or Decimal("0"))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.product.name} x {self.quantity}"


# -----------------------------------
# Listas de compra (flujo público)
# -----------------------------------
class PurchaseList(models.Model):
    STATUS = (("draft", "Draft"), ("final", "Final"))

    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.PROTECT, related_name="lists"
    )
    series_code = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS, default="draft")
    notes = models.TextField(blank=True, null=True)         # notas generales (PDF)
    observation = models.TextField(blank=True, null=True)   # observación interna
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finalized_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.series_code or 'DRAFT'} - {self.restaurant.code}"


class PurchaseListItem(models.Model):
    purchase_list = models.ForeignKey(
        PurchaseList, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)

    # Regla: si la unidad es moneda, qty es el **importe**; en otro caso, qty es la cantidad
    qty = models.DecimalField(max_digits=12, decimal_places=2)
    price_soles = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit = models.ForeignKey('Unit', on_delete=models.PROTECT)

    class Meta:
        indexes = [
            models.Index(fields=["purchase_list", "product"]),
        ]

    def clean(self):
    # Validaciones coherentes según tipo de unidad
        if self.unit and self.unit.is_currency:
            # Moneda: qty = importe; price_soles no debe venir
            if self.price_soles not in (None, Decimal("0"), Decimal("0.00")):
                raise ValidationError(
                    "Para unidad monetaria, no debe enviarse price_soles (use solo qty como importe)."
                )
        else:
            # No moneda:
            # Permitir price_soles vacío mientras la lista esté en borrador (draft).
            # Exigir price_soles solo cuando la lista se vaya a finalizar.
            if self.purchase_list and self.purchase_list.status == "final" and self.price_soles is None:
                raise ValidationError(
                    "price_soles es obligatorio para unidades no monetarias al finalizar la lista."
                )

    @property
    def subtotal_soles(self):
        # Si la unidad es monetaria, el subtotal ES la cantidad
        if self.unit and getattr(self.unit, "is_currency", False):
            return self.qty or Decimal('0')
        # Si no es monetaria, multiplicamos con tolerancia a None
        q = self.qty or Decimal('0')
        p = self.price_soles or Decimal('0')
        return q * p

    def __str__(self) -> str:
        return f"{self.product.name} ({self.unit.name})"
