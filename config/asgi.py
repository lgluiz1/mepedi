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

application = get_asgi_application()
