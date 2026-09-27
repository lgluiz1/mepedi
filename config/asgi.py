"""
ASGI config for IA-Pedidos project.
"""
import os
import sys
from pathlib import Path
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

base_dir = Path(__file__).resolve().parent.parent
apps_dir = base_dir / 'apps'
if str(apps_dir) not in sys.path:
    sys.path.insert(0, str(apps_dir))

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import orders.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            orders.routing.websocket_urlpatterns
        )
    ),
})
