from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from django.views.generic.edit import CreateView

from tournaments import models


class IndexView(ListView):

    context_object_name = 'tournaments'
    queryset = models.Tournament.objects
    template_name = 'frontend/index.html'


class CreateTournamentView(LoginRequiredMixin, CreateView):

    model = models.Tournament
    template_name = 'frontend/create-tournament.html'
    fields = [
        'name',
        'podium_spec',
    ]
