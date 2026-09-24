from django.urls import path
from . import views

app_name = 'stores'

urlpatterns = [
    # Endpoint público por slug
    path('public/<slug:slug>/', views.StorePublicDetailView.as_view(), name='public-detail'),
    # Endpoints administrativos do lojista
    path('merchant/', views.MerchantStoreListCreateView.as_view(), name='merchant-list-create'),
    path('merchant/<int:id>/', views.MerchantStoreDetailUpdateView.as_view(), name='merchant-detail-update'),
]
