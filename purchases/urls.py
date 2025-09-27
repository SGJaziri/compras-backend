# purchases/urls.py
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView

from rest_framework_nested import routers

router = routers.DefaultRouter()
router.register("purchase-lists", PurchaseListViewSet, basename="purchase-list")

nested = routers.NestedDefaultRouter(router, "purchase-lists", lookup="purchase_list")
nested.register("items", PurchaseListItemViewSet, basename="purchase-list-items")

urlpatterns = [
    path("api/", include(router.urls)),
    path("api/", include(nested.urls)),
    path('admin/', admin.site.urls),
]

# (Opcional) redirecciones sin barra final
urlpatterns += [
    re_path(
        r'^api/purchase-lists/export/range$',
        RedirectView.as_view(url='/api/purchase-lists/export/range/', permanent=True)
    ),
    re_path(
        r'^api/purchase-lists/export/by-date$',
        RedirectView.as_view(url='/api/purchase-lists/export/by-date/', permanent=True)
    ),
]
