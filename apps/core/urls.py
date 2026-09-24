from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.platform_home, name='home'),
    path('health/', views.health_check, name='health_check'),
]
