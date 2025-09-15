# core/views.py
from django.utils import timezone

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, authentication_classes, permission_classes
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


# ---------------------------
# Utilidad de permisos por defecto (admin)
# ---------------------------
class DefaultPerm(permissions.IsAuthenticated):
    pass


# ---------------------------
# PUBLIC CONFIG (sin login)
# ---------------------------
class PublicConfigView(APIView):
    """
    Devuelve configuración mínima para el builder público:
    - restaurantes, categorías, productos, unidades
    """
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


# ---------------------------
# Catálogo / Admin
# ---------------------------
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
    """CRUD de unidades (admin)."""
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    permission_classes = [DefaultPerm]


# ---------------------------
# Compras formales (futuro)
# ---------------------------
class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.prefetch_related('items').all()
    serializer_class = PurchaseSerializer
    permission_classes = [DefaultPerm]

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        # stub para PDF — Sprint siguiente
        return Response({'detail': 'PDF no implementado aún'}, status=200)


# ---------------------------
# LISTAS DE COMPRA (flujo público)
# ---------------------------
class PurchaseListViewSet(viewsets.ModelViewSet):
    """
    - create  (POST /purchase-lists/)         -> público temporal
    - items   (POST /purchase-lists/{id}/items/) -> público temporal
    - finalize(POST /purchase-lists/{id}/finalize/) -> público temporal
    El resto de acciones quedan protegidas por defecto.
    """
    queryset = PurchaseList.objects.prefetch_related('items', 'restaurant').all()
    serializer_class = PurchaseListSerializer
    permission_classes = [permissions.IsAuthenticated]  # protegido por defecto

    # Público temporal para V1 (builder sin login):
    def get_permissions(self):
        if self.action in ['create', 'add_item', 'finalize']:
            return [permissions.AllowAny()]
        return super().get_permissions()

    # Hacemos create explícitamente sin autenticación/CSRF
    @authentication_classes([])
    @permission_classes([permissions.AllowAny])
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @authentication_classes([])
    @permission_classes([permissions.AllowAny])
    @action(detail=True, methods=['post'], url_path='finalize')
    def finalize(self, request, pk=None):
        pl = self.get_object()
        if pl.status == "final":
            return Response(
                {"detail": "La lista ya está finalizada."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not pl.series_code:
            pl.series_code = generate_series_code(pl.restaurant.code, PurchaseList)

        pl.status = "final"
        pl.finalized_at = timezone.now()
        pl.save()
        return Response(PurchaseListSerializer(pl).data, status=200)

    @authentication_classes([])
    @permission_classes([permissions.AllowAny])
    @action(detail=True, methods=['post'], url_path='items')
    def add_item(self, request, pk=None):
        """Agregar ítem a la lista (builder público)."""
        pl = self.get_object()
        if pl.status == "final":
            return Response(
                {"detail": "No se pueden editar listas finalizadas."},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = request.data.copy()
        data['purchase_list'] = pl.id
        ser = PurchaseListItemSerializer(data=data)
        if ser.is_valid():
            ser.save()
            return Response(ser.data, status=201)
        return Response(ser.errors, status=400)
