from django.db import models
from django.utils import timezone
from decimal import Decimal


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    def __str__(self): return self.name

class Restaurant(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=10, unique=True)
    def __str__(self): return f"{self.code} - {self.name}"

class Product(models.Model):
    name = models.CharField(max_length=150)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    supplier = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name

class Purchase(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name='purchases')
    serial = models.CharField(max_length=32, unique=True)
    issue_date = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    class Meta:
        ordering = ['-issue_date']

class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def save(self, *args, **kwargs):
        self.line_total = self.quantity * self.unit_price
        super().save(*args, **kwargs)