from django.contrib import admin
from .models import DeliveryZone


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'fee', 'estimated_time_min', 'estimated_time_max', 'is_active')
    list_filter = ('store', 'is_active')
    search_fields = ('name', 'neighborhoods', 'store__name')
    ordering = ('store', 'fee')
