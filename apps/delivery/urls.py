from django.urls import path
from . import views

app_name = 'delivery'

urlpatterns = [
    # Rotas públicas
    path('public/<slug:store_slug>/zones/', views.PublicDeliveryZoneListView.as_view(), name='public-zones-list'),
    path('public/<slug:store_slug>/calculate-fee/', views.PublicCalculateDeliveryFeeView.as_view(), name='public-calculate-fee'),

    # Rotas do lojista
    path('merchant/<int:store_id>/zones/', views.MerchantDeliveryZoneListCreateView.as_view(), name='merchant-zone-list-create'),
    path('merchant/<int:store_id>/zones/<int:id>/', views.MerchantDeliveryZoneDetailUpdateDeleteView.as_view(), name='merchant-zone-detail'),
]
