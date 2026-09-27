from django.contrib import admin
from .models import Feature, Plan, Subscription, PaymentGatewayConfig, PaymentHistory, WebhookEvent


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code', 'description')


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'price', 'billing_cycle', 'is_active', 'display_order', 'created_at')
    list_filter = ('billing_cycle', 'is_active')
    search_fields = ('name', 'slug', 'description')
    filter_horizontal = ('features',)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('store', 'plan', 'status', 'trial_ends_at', 'current_period_end', 'created_at')
    list_filter = ('status', 'trial_expired_reason')
    search_fields = ('store__name', 'external_customer_id', 'external_subscription_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PaymentGatewayConfig)
class PaymentGatewayConfigAdmin(admin.ModelAdmin):
    list_display = ('gateway', 'environment', 'masked_access_token_display', 'is_active', 'created_at')
    list_filter = ('gateway', 'environment', 'is_active')

    def masked_access_token_display(self, obj):
        return obj.masked_access_token
    masked_access_token_display.short_description = 'Access Token (Mascarado)'


@admin.register(PaymentHistory)
class PaymentHistoryAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'gateway', 'external_id', 'amount', 'status', 'payment_date', 'created_at')
    list_filter = ('gateway', 'status')
    search_fields = ('subscription__store__name', 'external_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('gateway', 'external_id', 'event_type', 'status', 'processed_at', 'created_at')
    list_filter = ('gateway', 'status', 'event_type')
    search_fields = ('external_id', 'event_type')
    readonly_fields = ('created_at', 'updated_at')
