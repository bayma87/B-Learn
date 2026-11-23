from django.contrib import admin

from .models import AssessmentResult, ContactMessage, ItemConcluido, RegistroResiduo


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'created_at')
    search_fields = ('name', 'email', 'message')
    list_filter = ('created_at',)
    ordering = ('-created_at',)


@admin.register(AssessmentResult)
class AssessmentResultAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'overall_score', 'weakest_pillar', 'created_at')
    list_filter = ('weakest_pillar', 'created_at')
    search_fields = ('usuario__username',)
    ordering = ('-created_at',)


@admin.register(RegistroResiduo)
class RegistroResiduoAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'data', 'local', 'quantidade_kg', 'destino')
    list_filter = ('destino', 'data')
    search_fields = ('usuario__username', 'local')


@admin.register(ItemConcluido)
class ItemConcluidoAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'item_id', 'concluido_em')
    list_filter = ('item_id',)
    search_fields = ('usuario__username', 'item_id')
    ordering = ('-concluido_em',)
