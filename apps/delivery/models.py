from decimal import Decimal
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import StoreBoundedModel


class DeliveryZone(StoreBoundedModel):
    """
    Região ou zona de entrega configurada pela loja com taxa fixa e prazo estimado.
    Permite à loja cobrar taxas diferenciadas por bairros ou setores.
    """
    name = models.CharField(
        _('Nome da Região / Zona'),
        max_length=100,
        help_text=_('Ex: Centro, Zona Sul, Bairros Próximos')
    )
    neighborhoods = models.TextField(
        _('Bairros / Regiões Atendidas'),
        blank=True,
        help_text=_('Nomes dos bairros abrangidos por esta taxa, separados por vírgula.')
    )
    fee = models.DecimalField(
        _('Taxa de Entrega (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Valor do frete para esta região.')
    )
    estimated_time_min = models.PositiveIntegerField(
        _('Tempo Estimado Mínimo (min)'),
        default=30
    )
    estimated_time_max = models.PositiveIntegerField(
        _('Tempo Estimado Máximo (min)'),
        default=60
    )
    is_active = models.BooleanField(
        _('Zona Ativa'),
        default=True,
        help_text=_('Se desativada, a loja não fará entregas para esta região temporariamente.')
    )

    class Meta:
        verbose_name = _('Região de Entrega')
        verbose_name_plural = _('Regiões de Entrega')
        ordering = ['fee', 'name']

    def __str__(self):
        return f"{self.name} - R$ {self.fee:.2f} ({self.store.name})"

    def match_neighborhood(self, neighborhood_name: str) -> bool:
        """
        Verifica se um determinado bairro está listado nesta zona de entrega.
        """
        if not neighborhood_name or not self.neighborhoods:
            return False
        clean_target = neighborhood_name.strip().lower()
        items = [n.strip().lower() for n in self.neighborhoods.split(',') if n.strip()]
        return clean_target in items
