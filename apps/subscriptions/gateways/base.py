from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class PaymentGateway(ABC):
    """
    Interface abstrata para provedores de pagamento do SaaS MePedi.
    Permite desacoplar a lógica de negócio do SaaS de gateways específicos
    (Mercado Pago, Asaas, Stripe, etc).
    """

    def __init__(self, config=None):
        self.config = config

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Valida se as credenciais e a conectividade com o gateway estão funcionais.
        """
        pass

    @abstractmethod
    def create_customer(self, store, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria ou recupera o cliente no gateway de pagamento.
        """
        pass

    @abstractmethod
    def create_checkout_preference(self, subscription, plan, return_urls: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Gera uma preferência de checkout ou link de pagamento recorrente.
        """
        pass

    @abstractmethod
    def handle_webhook(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Normaliza os eventos recebidos via webhook em um formato padrão:
        {
            'event_type': 'payment.approved' | 'subscription.cancelled' | ...,
            'external_id': '...',
            'amount': Decimal('...'),
            'status': 'APPROVED' | 'REJECTED' | 'PENDING' | ...,
            'subscription_id': '...',
            'raw': payload
        }
        """
        pass
