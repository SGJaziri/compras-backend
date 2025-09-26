# purchases/urls.py
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),  # único include al core
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
