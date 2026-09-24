from django.urls import path
from . import views

app_name = 'catalog'

urlpatterns = [
    # Cardápio Público Mobile-First
    path('public/<slug:slug>/menu/', views.PublicStoreMenuView.as_view(), name='public-menu'),

    # Gestão de Categorias pelo Lojista
    path('merchant/<int:store_id>/categories/', views.MerchantCategoryListCreateView.as_view(), name='merchant-category-list-create'),
    path('merchant/<int:store_id>/categories/<int:id>/', views.MerchantCategoryDetailUpdateDeleteView.as_view(), name='merchant-category-detail'),

    # Gestão de Produtos pelo Lojista
    path('merchant/<int:store_id>/products/', views.MerchantProductListCreateView.as_view(), name='merchant-product-list-create'),
    path('merchant/<int:store_id>/products/<int:id>/', views.MerchantProductDetailUpdateDeleteView.as_view(), name='merchant-product-detail'),

    # Gestão de Grupos de Opções (Adicionais, Remoções, Variações)
    path('merchant/<int:store_id>/products/<int:product_id>/option-groups/', views.MerchantOptionGroupListCreateView.as_view(), name='merchant-option-group-list-create'),
    path('merchant/<int:store_id>/option-groups/<int:id>/', views.MerchantOptionGroupDetailView.as_view(), name='merchant-option-group-detail'),

    # Gestão de Itens de Opção
    path('merchant/<int:store_id>/option-groups/<int:group_id>/items/', views.MerchantOptionItemListCreateView.as_view(), name='merchant-option-item-list-create'),
    path('merchant/<int:store_id>/items/<int:id>/', views.MerchantOptionItemDetailView.as_view(), name='merchant-option-item-detail'),
]
