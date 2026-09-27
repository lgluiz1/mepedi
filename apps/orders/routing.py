from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/orders/(?P<store_id>\w+)/$', consumers.OrderDashboardConsumer.as_asgi()),
]
