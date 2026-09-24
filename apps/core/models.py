import uuid
from django.db import models


class TimeStampedModel(models.Model):
    """
    Modelo abstrato base que fornece campos de auditoria temporal.
    """
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        abstract = True
        ordering = ['-created_at']


class UUIDModel(models.Model):
    """
    Modelo abstrato que fornece um identificador UUID público seguro.
    """
    public_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
        verbose_name="ID Público"
    )

    class Meta:
        abstract = True


class StoreBoundedModel(TimeStampedModel):
    """
    Modelo abstrato para garantir o isolamento lógico multi-tenancy.
    Toda entidade atrelada a uma loja deve herdar desta classe.
    """
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        verbose_name="Loja",
        db_index=True
    )

    class Meta:
        abstract = True
