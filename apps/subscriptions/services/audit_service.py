import logging
from ..models import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """
    Serviço central de registro da trilha de auditoria do SaaS MePedi.
    Registra ações de suporte, alterações contratuais, financeiras e de gateways.
    """

    @classmethod
    def get_client_ip(cls, request):
        """
        Extrai o IP real do cliente considerando possíveis proxies reversos (Nginx/Cloudflare).
        """
        if not request:
            return None
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    @classmethod
    def log(cls, action, user=None, store=None, details=None, request=None):
        """
        Registra uma ação administrativa de forma segura e não bloqueante.
        """
        try:
            ip = cls.get_client_ip(request) if request else None
            effective_user = user
            if not effective_user and request and getattr(request, 'user', None) and request.user.is_authenticated:
                effective_user = request.user

            return AuditLog.objects.create(
                action=action,
                user=effective_user,
                store=store,
                ip_address=ip,
                details=details or {}
            )
        except Exception as e:
            logger.error(f"Falha ao registrar auditoria para ação {action}: {e}", exc_info=True)
            return None
