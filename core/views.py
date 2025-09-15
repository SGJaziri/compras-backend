from rest_framework import viewsets, permissions, decorators, response
from .models import Category, Product, Restaurant, Purchase
from .serializers import CategorySerializer, ProductSerializer, RestaurantSerializer, PurchaseSerializer

class DefaultPerm(permissions.IsAuthenticated): pass

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

class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.prefetch_related('items').all()
    serializer_class = PurchaseSerializer
    permission_classes = [DefaultPerm]

    @decorators.action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        # stub para PDF — Sprint 2
        return response.Response({'detail': 'PDF no implementado aún'}, status=200)