from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from core.models import TimeStampedModel, StoreBoundedModel
from .utils import generate_unique_slug


class Store(TimeStampedModel):
    """
    Entidade central do SaaS Multi-Loja.
    Representa o estabelecimento comercial e seu isolamento lógico.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='owned_stores',
        verbose_name=_('Proprietário')
    )
    name = models.CharField(
        _('Nome do Estabelecimento'),
        max_length=150,
        help_text=_('Ex: Lanchonete do Luiz')
    )
    slug = models.SlugField(
        _('Slug / URL Amigável'),
        max_length=160,
        unique=True,
        db_index=True,
        help_text=_('Identificador da URL pública da loja (ex: lanchonete-do-luiz)')
    )
    document = models.CharField(
        _('CPF ou CNPJ'),
        max_length=20,
        blank=True,
        help_text=_('Documento fiscal do lojista ou empresa.')
    )
    phone = models.CharField(
        _('Telefone Fixo / Comercial'),
        max_length=20,
        blank=True
    )
    whatsapp = models.CharField(
        _('WhatsApp para Pedidos'),
        max_length=20,
        help_text=_('Número que receberá as notificações e mensagens de pedidos.')
    )
    description = models.TextField(
        _('Descrição da Loja'),
        blank=True,
        help_text=_('Apresentação exibida no topo do cardápio digital.')
    )

    # Identidade Visual
    logo = models.ImageField(
        _('Logotipo'),
        upload_to='stores/logos/',
        blank=True,
        null=True
    )
    banner = models.ImageField(
        _('Banner de Cabeçalho'),
        upload_to='stores/banners/',
        blank=True,
        null=True
    )

    # Endereço Comercial
    street = models.CharField(_('Rua / Logradouro'), max_length=150, blank=True)
    number = models.CharField(_('Número'), max_length=20, blank=True)
    complement = models.CharField(_('Complemento'), max_length=100, blank=True)
    neighborhood = models.CharField(_('Bairro'), max_length=100, blank=True)
    city = models.CharField(_('Cidade'), max_length=100, blank=True)
    state = models.CharField(_('Estado (UF)'), max_length=2, blank=True)
    postal_code = models.CharField(_('CEP'), max_length=10, blank=True)

    # Operação e Status
    is_active = models.BooleanField(
        _('Loja Ativa na Plataforma'),
        default=True,
        help_text=_('Define se a loja pode operar no SaaS.')
    )
    is_open = models.BooleanField(
        _('Aberta para Pedidos'),
        default=False,
        help_text=_('Controle manual de abertura da loja.')
    )
    is_paused = models.BooleanField(
        _('Pedidos Pausados'),
        default=False,
        help_text=_('Pausa temporária de novos pedidos (ex: cozinha lotada).')
    )

    # Configurações Comerciais
    minimum_order_value = models.DecimalField(
        _('Valor Mínimo do Pedido'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    estimated_delivery_time_min = models.PositiveIntegerField(
        _('Tempo Estimado Mínimo (min)'),
        default=30
    )
    estimated_delivery_time_max = models.PositiveIntegerField(
        _('Tempo Estimado Máximo (min)'),
        default=60
    )

    # Modalidades de Atendimento
    allows_delivery = models.BooleanField(
        _('Aceita Entrega / Delivery'),
        default=True
    )
    allows_pickup = models.BooleanField(
        _('Aceita Retirada no Local'),
        default=True
    )

    class Meta:
        verbose_name = _('Loja')
        verbose_name_plural = _('Lojas')
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(Store, self.name, current_id=self.pk)
        super().save(*args, **kwargs)

    @property
    def full_address(self):
        parts = [self.street, self.number, self.neighborhood, self.city, self.state]
        return ", ".join([p for p in parts if p])

    def is_currently_open(self, at_datetime=None) -> bool:
        """
        Calcula dinamicamente se a loja está aberta para receber pedidos.
        Leva em consideração:
        1. Se a loja está ativa na plataforma.
        2. Se os pedidos estão pausados temporariamente (botão de pausa).
        3. Abertura manual direta (is_open=True).
        4. Grade semanal de horários de funcionamento (BusinessHour).
        """
        from django.utils import timezone

        if not self.is_active or self.is_paused:
            return False

        # Se o lojista abriu manualmente, está aberta
        if self.is_open:
            return True

        # Verifica pela grade horária
        now = at_datetime or timezone.localtime()
        weekday = now.weekday()
        current_time = now.time()

        schedule = self.business_hours.filter(weekday=weekday, is_closed=False).first()
        if schedule and schedule.opening_time and schedule.closing_time:
            if schedule.opening_time <= current_time <= schedule.closing_time:
                return True

        return False

    @property
    def status_label(self) -> str:
        if not self.is_active:
            return "Inativa"
        if self.is_paused:
            return "Pausada"
        if self.is_currently_open():
            return "Aberto"
        return "Fechado"


class BusinessHour(StoreBoundedModel):
    """
    Horário de funcionamento da loja por dia da semana.
    """
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='business_hours',
        verbose_name=_('Loja')
    )
    WEEKDAY_CHOICES = [
        (0, _('Segunda-feira')),
        (1, _('Terça-feira')),
        (2, _('Quarta-feira')),
        (3, _('Quinta-feira')),
        (4, _('Sexta-feira')),
        (5, _('Sábado')),
        (6, _('Domingo')),
    ]

    weekday = models.IntegerField(_('Dia da Semana'), choices=WEEKDAY_CHOICES)
    opening_time = models.TimeField(_('Horário de Abertura'), null=True, blank=True)
    closing_time = models.TimeField(_('Horário de Fechamento'), null=True, blank=True)
    is_closed = models.BooleanField(_('Fechado o Dia Todo'), default=False)

    class Meta:
        verbose_name = _('Horário de Funcionamento')
        verbose_name_plural = _('Horários de Funcionamento')
        unique_together = ('store', 'weekday')
        ordering = ['store', 'weekday']

    def __str__(self):
        day_name = dict(self.WEEKDAY_CHOICES).get(self.weekday, str(self.weekday))
        if self.is_closed:
            return f"{self.store.name} - {day_name}: Fechado"
        return f"{self.store.name} - {day_name}: {self.opening_time} às {self.closing_time}"
