from django.db.models.signals import post_save
from django.dispatch import receiver
from stores.models import Store
from .services.subscription_service import SubscriptionService


@receiver(post_save, sender=Store)
def auto_start_store_trial(sender, instance, created, **kwargs):
    """
    Ao criar uma nova loja no MePedi, inicia automaticamente o período de Trial gratuito
    de 30 dias (limite de 300 pedidos ou R$ 2.000 em vendas) com todas as features liberadas.
    """
    if created:
        SubscriptionService.start_trial(instance)
