# core/urls.py
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    PublicConfigView,
    CategoryViewSet, ProductViewSet, RestaurantViewSet, UnitViewSet,
    PurchaseViewSet, PurchaseListViewSet,
)

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'units', UnitViewSet, basename='unit')
router.register(r'restaurants', RestaurantViewSet, basename='restaurant')
router.register(r'purchases', PurchaseViewSet, basename='purchase')
router.register(r'purchase-lists', PurchaseListViewSet, basename='purchase-list')

urlpatterns = [
    path('public/config/', PublicConfigView.as_view(), name='public-config'),
]

urlpatterns += router.urls
