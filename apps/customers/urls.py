from django.urls import path
from . import views

app_name = 'customers'

urlpatterns = [
    # Identificação pública no checkout pelo slug da loja
    path('public/<slug:store_slug>/identify/', views.PublicCustomerIdentifyView.as_view(), name='public-identify'),
    path('public/<slug:store_slug>/lookup/', views.PublicCustomerLookupView.as_view(), name='public-lookup'),

    # Gestão de clientes pelo lojista
    path('merchant/<int:store_id>/', views.MerchantCustomerListView.as_view(), name='merchant-customer-list'),
    path('merchant/<int:store_id>/<int:id>/', views.MerchantCustomerDetailView.as_view(), name='merchant-customer-detail'),
]
