from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q
from django.views.generic import DeleteView, ListView, View
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.edit import FormView
from django.shortcuts import redirect
from django.urls import reverse

from tournaments import models

from .forms import CreateTournamentForm, UpdateTournamentForm
from .git import get_head_info


class IsCreatorMixin(LoginRequiredMixin, UserPassesTestMixin):

    def test_func(self):
        object = self.get_object()
        return object.creator is not None and self.request.user is not None and object.creator.id == self.request.user.id


def create_breadcrumb(items):
    return [(f'<a href="{ item["url"] }">{ item["label"] }</a>' if item_idx + 1 < len(items) else item['label']) for item_idx, item in enumerate(items)]


class VersionInfoMixin:

    def get_context_data(self, **kwargs):
        context = super(VersionInfoMixin, self).get_context_data(**kwargs)
        context['version'] = get_head_info()
        return context


class IndexView(VersionInfoMixin, ListView):

    context_object_name = 'tournaments'
    queryset = models.Tournament.objects
    template_name = 'frontend/index.html'

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        context['breadcrumb'] = create_breadcrumb([
            dict(label = 'Index', url = reverse('index')),
        ])

        published_tournaments = self.queryset.filter(published = True).annotate(
            fixtures = Count('stages__fixtures'),
            podium_size = Count('participations', filter = Q(participations__podium_position__isnull = False)))

        context['drafts']   = self.queryset.filter(published = False, creator = self.request.user)
        context['open']     = published_tournaments.filter(fixtures = 0)
        context['active']   = published_tournaments.filter(fixtures__gte = 1, podium_size = 0)
        context['finished'] = published_tournaments.filter(podium_size__gte = 1)

        return context


class CreateTournamentView(LoginRequiredMixin, VersionInfoMixin, FormView):

    form_class = CreateTournamentForm
    template_name = 'frontend/create-tournament.html'

    def form_valid(self, form):
        tournament = form.create_tournament(self.request)
        return redirect('update-tournament', pk = tournament.id)

    def get_context_data(self, **kwargs):
        context = super(CreateTournamentView, self).get_context_data(**kwargs)
        context['breadcrumb'] = create_breadcrumb([
            dict(label = 'Index', url = reverse('index')),
            dict(label = 'Create Tournament', url = self.request.path),
        ])
        return context


class UpdateTournamentView(IsCreatorMixin, SingleObjectMixin, VersionInfoMixin, FormView):

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

    def get_context_data(self, **kwargs):
        context = super(UpdateTournamentView, self).get_context_data(**kwargs)
        context['breadcrumb'] = create_breadcrumb([
            dict(label = 'Index', url = reverse('index')),
            dict(label = self.object.name, url = self.request.path),
        ])
        return context


class PublishTournamentView(IsCreatorMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.published = True
        self.object.save()
        return redirect('update-tournament', pk = self.object.id)


class DraftTournamentView(IsCreatorMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.published = False
        self.object.participations.all().delete()
        self.object.save()
        return redirect('update-tournament', pk = self.object.id)


class DeleteTournamentView(IsCreatorMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.stages.non_polymorphic().all().delete()
        self.object.delete()
        return redirect('index')


class JoinTournamentView(LoginRequiredMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.state == 'open':
            models.Participation.objects.create(
                tournament = self.object,
                user = self.request.user,
                slot_id = models.Participation.next_slot_id(self.object))
        return redirect('update-tournament', pk = self.object.id)


class WithdrawTournamentView(LoginRequiredMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.state == 'open':
            models.Participation.objects.filter(user = request.user).delete()
        return redirect('update-tournament', pk = self.object.id)
