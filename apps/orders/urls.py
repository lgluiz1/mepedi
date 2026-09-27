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
]
