# core/views.py
from django.utils import timezone

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Category, Product, Restaurant, Purchase,
    PurchaseList, PurchaseListItem, Unit
)
from .serializers import (
    CategorySerializer, ProductSerializer, RestaurantSerializer, PurchaseSerializer,
    PurchaseListSerializer, PurchaseListItemSerializer, UnitSerializer
)
from .services import generate_series_code


class DefaultPerm(permissions.IsAuthenticated):
    """Permiso por defecto para panel/admin."""
    pass


# --------- Público: config mínima ----------
class PublicConfigView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        restaurants = Restaurant.objects.all().order_by("name")
        categories = Category.objects.all().order_by("name")
        products = Product.objects.select_related("category").all().order_by("name")
        units = Unit.objects.all().order_by("name")

        return Response({
            "restaurants": RestaurantSerializer(restaurants, many=True).data,
            "categories": CategorySerializer(categories, many=True).data,
            "products": ProductSerializer(products, many=True).data,
            "units": UnitSerializer(units, many=True).data,
        })


# --------- Catálogo / Admin ----------
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [DefaultPerm]


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related('category').all()
    serializer_class = ProductSerializer
    permission_classes = [DefaultPerm]


class RestaurantViewSet(viewsets.ModelViewSet):
    queryset = Restaurant.objects.all()
    serializer_class = RestaurantSerializer
    permission_classes = [DefaultPerm]


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    permission_classes = [DefaultPerm]


# --------- Compras formales (futuro) ----------
class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.prefetch_related('items').all()
    serializer_class = PurchaseSerializer
    permission_classes = [DefaultPerm]

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        return Response({'detail': 'PDF no implementado aún'}, status=200)


# --------- Listas (flujo público) ----------
class PurchaseListViewSet(viewsets.ModelViewSet):
    """
    Público temporal: create, add_item, finalize
    """
    queryset = PurchaseList.objects.prefetch_related('items', 'restaurant').all()
    serializer_class = PurchaseListSerializer
    # Protegido por defecto; abrimos solo acciones públicas:
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ['create', 'add_item', 'finalize']:
            return [permissions.AllowAny()]
        return super().get_permissions()

    # Aseguramos que create no use SessionAuth/CSRF
    authentication_classes = []  # aplica a create/update por defecto

    @action(
        detail=True, methods=['post'], url_path='finalize',
        permission_classes=[permissions.AllowAny], authentication_classes=[]
    )
    def finalize(self, request, pk=None):
        pl = self.get_object()
        if pl.status == "final":
            return Response(
                {"detail": "La lista ya está finalizada."},
                status=status.HTTP_400_BAD_REQUEST
            )
        else:
            if not pl.series_code:
                pl.series_code = generate_series_code(pl.restaurant.code, PurchaseList)
            pl.status = "final"
            pl.finalized_at = timezone.now()
            pl.save()
            return Response(PurchaseListSerializer(pl).data, status=200)

    @action(
        detail=True, methods=['post'], url_path='items',
        permission_classes=[permissions.AllowAny], authentication_classes=[]
    )
    def add_item(self, request, pk=None):
        """Agregar ítem a la lista (builder público)."""
        pl = self.get_object()
        if pl.status == "final":
            return Response(
                {"detail": "No se pueden editar listas finalizadas."},
                status=status.HTTP_400_BAD_REQUEST
            )
        else:
            data = request.data.copy()
            data['purchase_list'] = pl.id
            ser = PurchaseListItemSerializer(data=data)
            if ser.is_valid():
                ser.save()
                return Response(ser.data, status=201)
            return Response(ser.errors, status=400)
