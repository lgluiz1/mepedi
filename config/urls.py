"""
URL configuration for IA-Pedidos project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from stores.views import public_store_menu_view
from orders.views import public_checkout_page, public_order_status_page, public_customer_orders_page
from orders.dashboard_views import (
    merchant_login_view,
    merchant_logout_view,
    merchant_dashboard_root_view,
    merchant_dashboard_store_view,
    merchant_products_view,
    merchant_product_options_view,
    merchant_store_settings_view,
    merchant_pos_view,
)
from analytics.views import (
    merchant_analytics_view,
    create_trackable_link_view,
    track_event_api_view,
)
from whatsapp.views import order_whatsapp_redirect_view
from subscriptions.views import (
    merchant_subscription_view,
    merchant_subscription_checkout_view,
    merchant_subscription_return_view,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    # Rotas dos apps
    path('api/v1/accounts/', include('accounts.urls', namespace='accounts')),
    path('api/v1/stores/', include('stores.urls', namespace='stores')),
    path('api/v1/catalog/', include('catalog.urls', namespace='catalog')),
    path('api/v1/customers/', include('customers.urls', namespace='customers')),
    path('api/v1/delivery/', include('delivery.urls', namespace='delivery')),
    path('api/v1/orders/', include('orders.urls', namespace='orders')),
    path('api/v1/whatsapp/', include('whatsapp.urls', namespace='whatsapp')),
    path('api/v1/subscriptions/', include('subscriptions.urls', namespace='subscriptions')),
    path('api/v1/analytics/<slug:store_slug>/event/', track_event_api_view, name='analytics_track_event_api'),

    # Painel Administrativo Proprietário MePedi SaaS
    path('gestao-saas/', include('subscriptions.admin_urls', namespace='saas_admin')),

    # Painel do Lojista (Web Dashboard)
    path('painel/login/', merchant_login_view, name='merchant_login'),
    path('painel/logout/', merchant_logout_view, name='merchant_logout'),
    path('painel/', merchant_dashboard_root_view, name='merchant_dashboard_root'),
    path('painel/<slug:store_slug>/', merchant_dashboard_store_view, name='merchant_dashboard_store'),
    path('painel/<slug:store_slug>/pdv/', merchant_pos_view, name='merchant_pos'),
    path('painel/<slug:store_slug>/produtos/', merchant_products_view, name='merchant_products'),
    path('painel/<slug:store_slug>/produtos/<int:product_id>/opcoes/', merchant_product_options_view, name='merchant_product_options'),
    path('painel/<slug:store_slug>/configuracoes/', merchant_store_settings_view, name='merchant_store_settings'),
    path('painel/<slug:store_slug>/analytics/', merchant_analytics_view, name='merchant_analytics'),
    path('painel/<slug:store_slug>/analytics/links/create/', create_trackable_link_view, name='merchant_analytics_create_link'),
    path('painel/<slug:store_slug>/assinatura/', merchant_subscription_view, name='merchant_subscription'),
    path('painel/<slug:store_slug>/assinatura/checkout/<slug:plan_slug>/', merchant_subscription_checkout_view, name='merchant_subscription_checkout'),
    path('painel/<slug:store_slug>/assinatura/retorno/', merchant_subscription_return_view, name='merchant_subscription_return'),

    # Página institucional da plataforma
    path('', include('core.urls', namespace='core')),

    # Rotas públicas do cardápio e fluxo de pedidos da loja
    path('<slug:store_slug>/checkout/', public_checkout_page, name='public_checkout'),
    path('<slug:store_slug>/meus-pedidos/', public_customer_orders_page, name='public_customer_orders'),
    path('<slug:store_slug>/pedidos/<uuid:public_id>/whatsapp/', order_whatsapp_redirect_view, name='order_whatsapp_redirect'),
    path('<slug:store_slug>/pedidos/<uuid:public_id>/', public_order_status_page, name='public_order_status'),
    path('<slug:store_slug>/', public_store_menu_view, name='store_public_menu'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
