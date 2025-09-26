from django.urls import re_path
from django.views.generic import RedirectView

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
