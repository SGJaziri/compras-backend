from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    CategoryViewSet, ProductViewSet, RestaurantViewSet, UnitViewSet,
    PurchaseViewSet, PurchaseListViewSet, PublicConfigView
)

router = DefaultRouter()
router.register('categories', CategoryViewSet, basename='category')
router.register('products', ProductViewSet, basename='product')
router.register('restaurants', RestaurantViewSet, basename='restaurant')
router.register('units', UnitViewSet, basename='unit')
router.register('purchases', PurchaseViewSet, basename='purchase')
router.register('purchase-lists', PurchaseListViewSet, basename='purchase-list')

urlpatterns = router.urls + [
    path('public/config/', PublicConfigView.as_view(), name='public-config'),
]
