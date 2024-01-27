from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import models


class ParticipationInline(admin.TabularInline):
    model = models.Participation
    fields = ('user', 'slot_id', 'podium_position')


@admin.register(models.Tournament)
class TournamentAdmin(admin.ModelAdmin):

    list_display = ('name', 'published', 'creator')
    list_filter  = ('published', 'creator')

    fieldsets = (
        (None, {
            'fields': (
                'name',
                'definition',
                'podium_spec',
                'published',
                'creator')
            }
        ),
    )

    inlines = [
        ParticipationInline,
    ]
