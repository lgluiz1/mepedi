from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    # Rotas Públicas da API
    path('public/<slug:store_slug>/', views.PublicCreateOrderView.as_view(), name='public-create-order'),
    path('public/status/<uuid:public_id>/', views.PublicOrderDetailView.as_view(), name='public-order-detail'),
    path('coupon/validate/', views.ValidateCouponView.as_view(), name='validate-coupon'),

    # Rotas do Lojista (API REST)
    path('merchant/<int:store_id>/', views.MerchantOrderListView.as_view(), name='merchant-order-list'),
    path('merchant/<int:store_id>/<int:id>/', views.MerchantOrderDetailView.as_view(), name='merchant-order-detail'),
    path('merchant/<int:store_id>/<int:id>/status/', views.MerchantOrderUpdateStatusView.as_view(), name='merchant-order-update-status'),
    path('merchant/<int:store_id>/pos/', views.POSCreateOrderView.as_view(), name='merchant-pos-create-order'),

    # Rotas Públicas de Mesa (QR Code)
    path('table/<uuid:qr_token>/', views.PublicCreateTableOrderView.as_view(), name='public-create-table-order'),
    path('table/<uuid:qr_token>/identify/', views.PublicTableSessionIdentifyView.as_view(), name='public-table-session-identify'),
    path('table/<uuid:qr_token>/session-status/', views.PublicTableSessionStatusView.as_view(), name='public-table-session-status'),
    path('table/<uuid:qr_token>/comanda/', views.PublicTableComandaView.as_view(), name='public-table-comanda'),
    path('table/<uuid:qr_token>/pedir-conta/', views.PublicRequestTableBillView.as_view(), name='public-request-table-bill'),

    # Rotas do Lojista para Gestão de Itens, Mesas e Fechamento no PDV
    path('merchant/<int:store_id>/items/<int:item_id>/status/', views.MerchantOrderItemStatusUpdateView.as_view(), name='merchant-item-update-status'),
    path('merchant/<int:store_id>/tables/', views.MerchantTableListCreateView.as_view(), name='merchant-table-list-create'),
    path('merchant/<int:store_id>/tables/<int:table_id>/', views.MerchantTableDetailView.as_view(), name='merchant-table-detail'),
    path('merchant/<int:store_id>/tables/<int:table_id>/session/', views.MerchantActiveSessionByTableView.as_view(), name='merchant-table-active-session'),
    path('merchant/<int:store_id>/table-sessions/<uuid:session_id>/close/', views.MerchantTableSessionCloseView.as_view(), name='merchant-table-session-close'),
]

