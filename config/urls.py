"""
URL configuration for IA-Pedidos project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from stores.views import public_store_menu_view

urlpatterns = [
    path('admin/', admin.site.urls),
    # Rotas dos apps
    path('api/v1/accounts/', include('accounts.urls', namespace='accounts')),
    path('api/v1/stores/', include('stores.urls', namespace='stores')),
    path('api/v1/catalog/', include('catalog.urls', namespace='catalog')),
    path('api/v1/customers/', include('customers.urls', namespace='customers')),
    path('api/v1/delivery/', include('delivery.urls', namespace='delivery')),
    # Página institucional da plataforma
    path('', include('core.urls', namespace='core')),
    # Rota pública do cardápio digital da loja (ex: /lanchonete-do-luiz/)
    path('<slug:store_slug>/', public_store_menu_view, name='store_public_menu'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
