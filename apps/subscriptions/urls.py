from django.urls import path
from . import views

app_name = 'subscriptions'

urlpatterns = [
    path('webhook/<str:gateway>/', views.gateway_webhook_view, name='gateway_webhook'),
    path('checkout/<slug:store_slug>/<slug:plan_slug>/', views.merchant_subscription_checkout_view, name='checkout'),
    path('return/<slug:store_slug>/', views.merchant_subscription_return_view, name='return'),
]
