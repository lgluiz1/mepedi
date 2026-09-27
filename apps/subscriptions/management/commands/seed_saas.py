from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from stores.models import Store
from subscriptions.models import Subscription
from subscriptions.services.subscription_service import SubscriptionService


class Command(BaseCommand):
    help = 'Inicializa os dados padrão do SaaS MePedi (Features, Planos Comerciais e migração de transição para lojas existentes).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Iniciando seed idempotente do SaaS MePedi..."))

        result = SubscriptionService.seed_default_saas_data()
        features = result['features']
        plans = result['plans']

        self.stdout.write(self.style.SUCCESS(f"Features inicializadas com sucesso: {len(features)}"))
        for code, feat in features.items():
            self.stdout.write(f"  - [{code}] {feat.name}")

        self.stdout.write(self.style.SUCCESS(f"Planos Comerciais inicializados com sucesso: {len(plans)}"))
        for slug, plan in plans.items():
            self.stdout.write(f"  - Plano {plan.name}: R$ {plan.price}/mês ({plan.features.count()} features)")

        # Estratégia de transição para lojas existentes sem quebrar operações (Seção 26)
        existing_stores = Store.objects.all()
        migrated_count = 0
        for store in existing_stores:
            has_sub = Subscription.objects.filter(
                store=store,
                status__in=[Subscription.STATUS_TRIAL, Subscription.STATUS_ACTIVE, Subscription.STATUS_PAST_DUE]
            ).exists()
            if not has_sub:
                now = timezone.now()
                Subscription.objects.create(
                    store=store,
                    plan=None,
                    status=Subscription.STATUS_TRIAL,
                    trial_started_at=now,
                    trial_ends_at=now + timedelta(days=30),
                )
                migrated_count += 1
                self.stdout.write(self.style.WARNING(f"  * Loja existente '{store.name}' vinculada ao Trial de transição de 30 dias."))

        if migrated_count > 0:
            self.stdout.write(self.style.SUCCESS(f"Transição concluída: {migrated_count} lojas existentes preservadas em Trial."))
        else:
            self.stdout.write(self.style.NOTICE("Nenhuma loja órfã pendente de transição."))

        self.stdout.write(self.style.SUCCESS("SaaS MePedi seed finalizado com sucesso!"))
