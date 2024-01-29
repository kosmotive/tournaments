from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from django.utils.safestring import mark_safe

from . import models


class ParticipationInline(admin.TabularInline):
    model = models.Participation
    fields = ('user', 'slot_id', 'podium_position')

@admin.action(description='Reset active/finished tournament to open')
def reset_tournament(modeladmin, request, queryset):
    for tournament in queryset.all():
        if tournament.state not in ('active', 'finished'):
            continue
        for participation in tournament.participations.all():
            participation.podium_position = None
            participation.save()
        for stage in tournament.stages.all():
            stage.fixtures.all().delete()
        assert tournament.state == 'open'


@admin.register(models.Tournament)
class TournamentAdmin(admin.ModelAdmin):

    list_display = ('name', 'published', 'state', 'creator')
    list_filter  = ('published', 'creator')

    actions = [reset_tournament]

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


@admin.register(models.Fixture)
class FixtureAdmin(admin.ModelAdmin):

    list_display = ('id', 'tournament', 'mode', 'level', 'position', 'player1', 'player2', 'score')
    list_filter  = ('mode__tournament',)

    ordering = ('mode__tournament', 'mode', 'level', 'position')

    def tournament(self, fixture):
        url = reverse('admin:tournaments_tournament_change', args=(fixture.mode.tournament.pk,))
        return mark_safe(f'<a href="{ url }">{ fixture.mode.tournament.name }</a>')

    def score(self, fixture):
        return f'{fixture.score[0]}:{fixture.score[1]}' if fixture.score else '-'
