from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, View
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.edit import FormView
from django.shortcuts import redirect

from tournaments import models

from .forms import CreateTournamentForm, UpdateTournamentForm


class IndexView(ListView):

    context_object_name = 'tournaments'
    queryset = models.Tournament.objects
    template_name = 'frontend/index.html'


class CreateTournamentView(LoginRequiredMixin, FormView):

    form_class = CreateTournamentForm
    template_name = 'frontend/create-tournament.html'

    def form_valid(self, form):
        tournament = form.create_tournament(self.request)
        return redirect('update-tournament', pk = tournament.id)


class UpdateTournamentView(LoginRequiredMixin, SingleObjectMixin, FormView):

    form_class = UpdateTournamentForm
    template_name = 'frontend/update-tournament.html'
    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super(UpdateTournamentView, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super(UpdateTournamentView, self).post(request, *args, **kwargs)

    def form_valid(self, form):
        tournament = form.update_tournament(self.request, self.object)
        return redirect('update-tournament', pk = tournament.id)

    def get_form_kwargs(self):
        data = super().get_form_kwargs()
        data['initial'] = dict(
            name = self.get_object().name,
            definition = self.get_object().definition,
        )
        return data


class PublishTournamentView(LoginRequiredMixin, View):

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        # TODO: require that request.user is the owner
        self.object.published = True
        self.object.save()
        return redirect('update-tournament', pk = self.object.id)
