from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel
from .managers import CustomUserManager


class User(AbstractUser):
    """
    Modelo de usuário customizado da plataforma IA-Pedidos.
    Utiliza e-mail como credencial principal de autenticação.
    """
    username = models.CharField(
        _('username'),
        max_length=150,
        blank=True,
        null=True,
        help_text=_('Identificador amigável opcional.')
    )
    email = models.EmailField(
        _('endereço de e-mail'),
        unique=True,
        error_messages={
            'unique': _("Já existe um usuário cadastrado com este e-mail."),
        }
    )
    full_name = models.CharField(
        _('nome completo'),
        max_length=150,
        blank=True,
        help_text=_('Nome do responsável ou lojista.')
    )
    phone = models.CharField(
        _('telefone de contato'),
        max_length=20,
        blank=True,
        help_text=_('Telefone para contato do lojista.')
    )
    is_merchant = models.BooleanField(
        _('lojista'),
        default=True,
        help_text=_('Indica se o usuário possui acesso ao painel do comerciante.')
    )

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        verbose_name = _('Usuário')
        verbose_name_plural = _('Usuários')
        ordering = ['-date_joined']

    def __str__(self):
        return self.email or self.username or f"User #{self.pk}"

    def get_full_name(self):
        return self.full_name or self.email


class StoreMembership(TimeStampedModel):
    """
    Tabela de relacionamento entre Usuário e Loja, permitindo controle de papéis
    e colaboração futura (múltiplos operadores/atendentes na mesma loja).
    """
    ROLE_OWNER = 'owner'
    ROLE_ADMIN = 'admin'
    ROLE_ATTENDANT = 'attendant'

    ROLE_CHOICES = [
        (ROLE_OWNER, 'Proprietário'),
        (ROLE_ADMIN, 'Administrador'),
        (ROLE_ATTENDANT, 'Atendente'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name=_('Usuário')
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name=_('Loja')
    )
    role = models.CharField(
        _('Papel'),
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_OWNER
    )
    is_active = models.BooleanField(
        _('Ativo'),
        default=True
    )

    class Meta:
        verbose_name = _('Vínculo Usuário/Loja')
        verbose_name_plural = _('Vínculos Usuário/Loja')
        unique_together = ('user', 'store')

    def __str__(self):
        return f"{self.user.email} - {self.store.name} ({self.get_role_display()})"
