from django.urls import path
from .views import (
    merchant_analytics_view,
    create_trackable_link_view,
    track_event_api_view,
)

app_name = 'analytics'

urlpatterns = [
    path('painel/<slug:store_slug>/analytics/', merchant_analytics_view, name='merchant_analytics'),
    path('painel/<slug:store_slug>/analytics/links/create/', create_trackable_link_view, name='create_trackable_link'),
    path('api/v1/analytics/<slug:store_slug>/event/', track_event_api_view, name='track_event_api'),
]
