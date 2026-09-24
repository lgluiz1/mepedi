from django.contrib import admin
from .models import Category, Product, OptionGroup, OptionItem


class OptionItemInline(admin.TabularInline):
    model = OptionItem
    extra = 1
    fields = ('name', 'price', 'is_available', 'order')


class OptionGroupInline(admin.StackedInline):
    model = OptionGroup
    extra = 0
    fields = ('name', 'description', 'min_options', 'max_options', 'is_required', 'order')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'order', 'is_active', 'created_at')
    list_filter = ('store', 'is_active')
    search_fields = ('name', 'store__name')
    ordering = ('store', 'order', 'name')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'store', 'price', 'is_active', 'order')
    list_filter = ('store', 'category', 'is_active')
    search_fields = ('name', 'description', 'store__name')
    ordering = ('store', 'category', 'order', 'name')
    inlines = [OptionGroupInline]


@admin.register(OptionGroup)
class OptionGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'product', 'store', 'min_options', 'max_options', 'is_required', 'order')
    list_filter = ('store', 'is_required')
    search_fields = ('name', 'product__name', 'store__name')
    inlines = [OptionItemInline]


@admin.register(OptionItem)
class OptionItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'option_group', 'price', 'is_available', 'order')
    list_filter = ('is_available', 'option_group__product__store')
    search_fields = ('name', 'option_group__name')
