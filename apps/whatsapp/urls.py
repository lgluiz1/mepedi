from django.urls import path
from . import views

app_name = 'whatsapp'

urlpatterns = [
    path('orders/<uuid:public_id>/link/', views.OrderWhatsAppLinkAPIView.as_view(), name='order-link'),
]
