from rest_framework import serializers
from .models import Category, Product, Restaurant, Purchase, PurchaseItem, PurchaseList, PurchaseListItem, Unit
from .services.serials import next_serial_for
from django.utils import timezone

class CategorySerializer(serializers.ModelSerializer):
    class Meta: model = Category; fields = ['id', 'name']

class RestaurantSerializer(serializers.ModelSerializer):
    class Meta: model = Restaurant; fields = ['id', 'name', 'code']

class ProductSerializer(serializers.ModelSerializer):
    class Meta: model = Product; fields = ['id','name','category','unit_price','supplier','is_active']

class PurchaseItemInSerializer(serializers.ModelSerializer):
    class Meta: model = PurchaseItem; fields = ['product','quantity','unit_price']

class PurchaseSerializer(serializers.ModelSerializer):
    items = PurchaseItemInSerializer(many=True)
    class Meta:
        model = Purchase
        fields = ['id','restaurant','serial','issue_date','notes','total_amount','items']
        read_only_fields = ['serial','issue_date','total_amount']

class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = "__all__"

class PurchaseListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseListItem
        fields = "__all__"

    def validate(self, attrs):
        unit = attrs.get("unit")
        qty = attrs.get("qty")
        price = attrs.get("price_soles")

        if unit and unit.is_currency:
            # Moneda: qty = importe, no debe venir price
            if price not in (None, 0, 0.0):
                raise serializers.ValidationError("Para unidad monetaria, no envíes price_soles (usa qty como importe).")
        else:
            # No moneda: price obligatorio
            if price is None:
                raise serializers.ValidationError("price_soles es obligatorio cuando la unidad no es monetaria.")
        if qty is None or qty <= 0:
            raise serializers.ValidationError("qty debe ser mayor que 0.")
        return attrs

class PurchaseListSerializer(serializers.ModelSerializer):
    items = PurchaseListItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseList
        fields = "__all__"

def create(self, validated_data):
    items = validated_data.pop('items', [])
    restaurant = validated_data['restaurant']
    issue_date = timezone.now()
    serial = next_serial_for(restaurant, issue_date)
    purchase = Purchase.objects.create(serial=serial, issue_date=issue_date, **validated_data)
    total = 0
    for it in items:
        unit_price = it.get('unit_price')
        qty = it.get('quantity')
        line_total = qty * unit_price
        PurchaseItem.objects.create(purchase=purchase, line_total=line_total, **it)
        total += line_total
    purchase.total_amount = total
    purchase.save()
    return purchase