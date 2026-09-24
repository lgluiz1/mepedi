import re
from decimal import Decimal
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import StoreBoundedModel, TimeStampedModel


def clean_phone_number(phone_raw: str) -> str:
    """
    Remove caracteres não numéricos do telefone, garantindo formato consistente.
    Exemplo: '(11) 98888-7777' -> '11988887777'
    """
    if not phone_raw:
        return ""
    return re.sub(r'\D', '', str(phone_raw))


class Customer(StoreBoundedModel):
    """
    Cliente final associado a uma loja específica.
    O telefone é o identificador lógico principal por loja.
    Não utiliza senha para compra sem fricção no cardápio digital.
    """
    name = models.CharField(
        _('Nome do Cliente'),
        max_length=150
    )
    phone = models.CharField(
        _('Telefone (WhatsApp)'),
        max_length=20,
        db_index=True,
        help_text=_('Principal identificador do cliente nesta loja.')
    )
    document = models.CharField(
        _('CPF'),
        max_length=20,
        blank=True,
        help_text=_('Documento opcional do cliente.')
    )
    email = models.EmailField(
        _('E-mail'),
        blank=True
    )
    notes = models.TextField(
        _('Observações do Estabelecimento'),
        blank=True,
        help_text=_('Anotações internas sobre o cliente (ex: bom cliente, endereço de difícil acesso).')
    )

    # Métricas agregadas simples
    orders_count = models.PositiveIntegerField(
        _('Quantidade de Pedidos'),
        default=0
    )
    total_spent = models.DecimalField(
        _('Total Gasto (R$)'),
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00')
    )

    class Meta:
        verbose_name = _('Cliente')
        verbose_name_plural = _('Clientes')
        ordering = ['-created_at']
        unique_together = ('store', 'phone')

    def __str__(self):
        return f"{self.name} ({self.phone}) - {self.store.name}"

    def clean(self):
        super().clean()
        if self.phone:
            self.phone = clean_phone_number(self.phone)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class CustomerAddress(TimeStampedModel):
    """
    Endereço salvo de um cliente para entregas futuras.
    """
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='addresses',
        verbose_name=_('Cliente')
    )
    street = models.CharField(_('Rua / Logradouro'), max_length=150)
    number = models.CharField(_('Número'), max_length=20)
    complement = models.CharField(_('Complemento'), max_length=100, blank=True)
    neighborhood = models.CharField(_('Bairro'), max_length=100)
    city = models.CharField(_('Cidade'), max_length=100)
    state = models.CharField(_('Estado (UF)'), max_length=2)
    postal_code = models.CharField(_('CEP'), max_length=10, blank=True)
    reference = models.CharField(
        _('Ponto de Referência'),
        max_length=150,
        blank=True,
        help_text=_('Ex: Ao lado da padaria, portão cinza.')
    )
    is_default = models.BooleanField(
        _('Endereço Padrão'),
        default=False
    )

    class Meta:
        verbose_name = _('Endereço do Cliente')
        verbose_name_plural = _('Endereços dos Clientes')
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.street}, {self.number} - {self.neighborhood}, {self.city}/{self.state}"

    @property
    def formatted_address(self):
        base = f"{self.street}, {self.number}"
        if self.complement:
            base += f" ({self.complement})"
        base += f" - {self.neighborhood}, {self.city}/{self.state}"
        if self.reference:
            base += f" [Ref: {self.reference}]"
        return base
