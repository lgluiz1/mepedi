from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'subscriptions'
    verbose_name = 'SaaS & Assinaturas'

    def ready(self):
        try:
            import subscriptions.signals  # noqa
        except ImportError:
            pass
