import json
import logging
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


class OrderDashboardConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer para o Painel do Lojista.
    Recebe atualizações de novos pedidos (ONLINE e PDV) e mudanças de status em tempo real.
    Rota: ws/orders/<store_id>/
    """
    async def connect(self):
        self.store_id = self.scope['url_route']['kwargs'].get('store_id')
        self.group_name = f"store_{self.store_id}_orders"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()
        await self.send_json({
            "type": "CONNECTION_ESTABLISHED",
            "store_id": self.store_id,
            "message": "Conectado ao canal em tempo real de pedidos."
        })

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def receive_json(self, content):
        if content.get('type') == 'PING':
            await self.send_json({'type': 'PONG'})

    async def order_message(self, event):
        """
        Handler disparado pelo group_send('order.message', ...)
        """
        await self.send_json({
            "type": event.get("event"),
            "data": event.get("data")
        })


def broadcast_order_event(store_id, event_type, data):
    """
    Função utilitária síncrona para disparar eventos para o WebSocket
    a partir de services, views ou models do Django.
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"store_{store_id}_orders",
                {
                    "type": "order.message",
                    "event": event_type,
                    "data": data
                }
            )
    except Exception as e:
        logger.error(f"Erro ao transmitir evento WebSocket ({event_type}): {e}")
