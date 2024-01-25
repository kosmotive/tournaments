from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q
from django.views.generic import DeleteView, ListView, View
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.edit import FormView
from django.shortcuts import redirect

from tournaments import models

from .forms import CreateTournamentForm, UpdateTournamentForm


class IsCreatorMixin(LoginRequiredMixin, UserPassesTestMixin):

    def test_func(self):
        object = self.get_object()
        return object.creator is not None and self.request.user is not None and object.creator.id == self.request.user.id


class IndexView(ListView):

    context_object_name = 'tournaments'
    queryset = models.Tournament.objects
    template_name = 'frontend/index.html'

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        published_tournaments = self.queryset.filter(published = True).annotate(
            fixtures = Count('stages__fixtures'),
            podium = Count('participations', filter = Q(participations__podium_position__isnull = False)))

        context['drafts']   = self.queryset.filter(published = False)
        context['open']     = published_tournaments.filter(fixtures = 0)
        context['active']   = published_tournaments.filter(fixtures__gte = 1, podium = 0)
        context['finished'] = published_tournaments.filter(podium__gte = 1)

        return context


class CreateTournamentView(LoginRequiredMixin, FormView):

    form_class = CreateTournamentForm
    template_name = 'frontend/create-tournament.html'

    def form_valid(self, form):
        tournament = form.create_tournament(self.request)
        return redirect('update-tournament', pk = tournament.id)


class UpdateTournamentView(IsCreatorMixin, SingleObjectMixin, FormView):

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


class PublishTournamentView(IsCreatorMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.published = True
        self.object.save()
        return redirect('update-tournament', pk = self.object.id)


class DeleteTournamentView(IsCreatorMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.stages.all().delete()
        self.object.delete()
        return redirect('index')
