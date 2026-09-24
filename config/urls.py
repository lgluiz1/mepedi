"""
URL configuration for IA-Pedidos project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from stores.views import public_store_menu_view
from orders.views import public_checkout_page, public_order_status_page

urlpatterns = [
    path('admin/', admin.site.urls),
    # Rotas dos apps
    path('api/v1/accounts/', include('accounts.urls', namespace='accounts')),
    path('api/v1/stores/', include('stores.urls', namespace='stores')),
    path('api/v1/catalog/', include('catalog.urls', namespace='catalog')),
    path('api/v1/customers/', include('customers.urls', namespace='customers')),
    path('api/v1/delivery/', include('delivery.urls', namespace='delivery')),
    path('api/v1/orders/', include('orders.urls', namespace='orders')),
    # Página institucional da plataforma
    path('', include('core.urls', namespace='core')),
    # Rotas públicas do cardápio e fluxo de pedidos da loja
    path('<slug:store_slug>/checkout/', public_checkout_page, name='public_checkout'),
    path('<slug:store_slug>/pedidos/<uuid:public_id>/', public_order_status_page, name='public_order_status'),
    path('<slug:store_slug>/', public_store_menu_view, name='store_public_menu'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
