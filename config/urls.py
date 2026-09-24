"""
URL configuration for IA-Pedidos project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    # Rotas dos apps que serão desenvolvidos
    path('api/v1/accounts/', include('accounts.urls', namespace='accounts')),
    path('api/v1/stores/', include('stores.urls', namespace='stores')),
    path('api/v1/catalog/', include('catalog.urls', namespace='catalog')),
    # Página inicial/healthcheck
    path('', include('core.urls', namespace='core')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
