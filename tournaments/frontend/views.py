from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import ListView, View
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.edit import FormView

from tournaments import models

from .forms import CreateTournamentForm, SignupForm, UpdateTournamentForm
from .git import get_head_info


class IsCreatorMixin(LoginRequiredMixin, UserPassesTestMixin):

    def test_func(self):
        object = self.get_object()
        return object.creator is not None and self.request.user is not None and object.creator.id == self.request.user.id


def create_breadcrumb(items):
    return [(f'<a href="{ item["url"] }">{ item["label"] }</a>' if item_idx + 1 < len(items) else item['label']) for item_idx, item in enumerate(items)]


class VersionInfoMixin:

    version = get_head_info()

    def get_context_data(self, **kwargs):
        if hasattr(super(VersionInfoMixin, self), 'get_context_data'):
            context = super(VersionInfoMixin, self).get_context_data(**kwargs)
        else:
            context = dict()
        context['version'] = self.version
        return context


class AlertMixin:

    def get_context_data(self, **kwargs):
        if hasattr(super(AlertMixin, self), 'get_context_data'):
            context = super(AlertMixin, self).get_context_data(**kwargs)
        else:
            context = dict()
        if 'alert' in self.request.session:
            context['alert'] = self.request.session['alert']
            del self.request.session['alert']
        return context


class SignupView(VersionInfoMixin, View):

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        context['form'] = SignupForm()
        return render(request, 'frontend/signup.html', context)

    def post(self, request, *args, **kwargs):
        form = SignupForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=password)
            login(request, user)
            return redirect('index')
        else:
            return render(request, 'frontend/signup.html', dict(form = form))


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

        context['drafts']   = self.queryset.filter(published = False, creator = self.request.user) if self.request.user.id else list()
        context['open']     = published_tournaments.filter(fixtures = 0)
        context['active']   = published_tournaments.filter(fixtures__gte = 1, podium_size = 0)
        context['finished'] = published_tournaments.filter(podium_size__gte = 1)

        context['allstars'] = [models.Participation.objects.filter(podium_position = position).annotate(count = Count('participant__name')) for position in range(3)]
        if not any(context['allstars']):
            context['allstars'] = None

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


class UpdateTournamentView(IsCreatorMixin, SingleObjectMixin, VersionInfoMixin, AlertMixin, FormView):

    form_class = UpdateTournamentForm
    template_name = 'frontend/update-tournament.html'
    model = models.Tournament

    def test_func(self):
        if self.request.method == 'GET' and self.get_object().state != 'draft':
            return True
        else:
            return super(UpdateTournamentView, self).test_func()

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super(UpdateTournamentView, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Check whether the tournament is in "draft" state.
        if self.object.state != 'draft':
            return HttpResponse(status = 412)

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

        # Check whether the tournament is in "draft" state.
        if self.object.state != 'draft':
            return HttpResponse(status = 412)

        self.object.published = True
        self.object.save()
        request.session['alert'] = dict(status = 'success', text = 'The tournament is now open and can be joined by you and others.')
        return redirect('update-tournament', pk = self.object.id)


class DraftTournamentView(IsCreatorMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Check whether the tournament is in "open" state.
        if self.object.state != 'open':
            return HttpResponse(status = 412)

        self.object.published = False
        self.object.participations.all().delete()
        self.object.save()
        request.session['alert'] = dict(status = 'warning', text = 'The tournament is now in draft mode and cannot be joined.')
        return redirect('update-tournament', pk = self.object.id)


class DeleteTournamentView(IsCreatorMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Check whether the tournament is in "draft" state.
        if self.object.state != 'draft':
            return HttpResponse(status = 412)

        self.object.delete()
        return redirect('index')


class JoinTournamentView(LoginRequiredMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Check whether the tournament is in "open" state.
        if self.object.state != 'open':
            return HttpResponse(status = 412)

        # Create the participation only if it does not already exist.
        if not self.object.participations.filter(participant__user = request.user).exists():
            participant, created = models.Participant.objects.get_or_create(user = request.user, defaults = {'name': request.user.username})
            models.Participation.objects.create(
                tournament = self.object,
                participant = participant,
                slot_id = models.Participation.next_slot_id(self.object))

        request.session['alert'] = dict(status = 'success', text = 'You have joined the tournament.')
        return redirect('update-tournament', pk = self.object.id)


class WithdrawTournamentView(LoginRequiredMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Check whether the tournament is in "open" state.
        if self.object.state != 'open':
            return HttpResponse(status = 412)

        # Delete the participation only if it exists.
        if self.object.participations.filter(participant__user = request.user).exists():
            self.object.participations.filter(participant__user = request.user).delete()

        request.session['alert'] = dict(status = 'success', text = 'You have withdrawn from the tournament.')
        return redirect('update-tournament', pk = self.object.id)


class ManageParticipantsView(IsCreatorMixin, SingleObjectMixin, VersionInfoMixin, AlertMixin, View):

    model = models.Tournament
    template_name = 'frontend/manage-participants.html'
        
    def dispatch(self, *args, **kwargs):
        self.object = self.get_object()

        # Check whether the tournament is in "open" state.
        if self.get_object().state != 'open':
            return HttpResponse(status = 412)
        
        return super().dispatch(*args, **kwargs)

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        participant_names = request.POST.get('participant_names')
        if participant_names:
            participant_names_list = list(filter(lambda s: len(s) > 0, map(lambda s: s.strip(), participant_names.splitlines())))

            # Remove participations that are no longer on the list.
            for participation in list(self.object.participations.all()):
                if participation.participant.name not in participant_names_list:
                    participation.delete()

            # Remove participants that are no longer part of any tournament, and not associated with any user.
            models.Participant.objects.annotate(participations_count = Count('participations')).filter(participations_count = 0, user__isnull = True).delete()

            # Create new participants and participations.
            for participant_name in participant_names_list:

                # Check whether there is a user with the same name.
                if models.User.objects.filter(username = participant_name).exists():
                    user = models.User.objects.get(username = participant_name)
                    participant = models.Participant.get_or_create_for_user(user)
                else:
                    participant = models.Participant.objects.get_or_create(name = participant_name)[0]

                # Create a participation only if it does not already exist.
                if not self.object.participations.filter(participant = participant).exists():
                    models.Participation.objects.create(
                        tournament = self.object,
                        participant = participant,
                        slot_id = models.Participation.next_slot_id(self.object)
                    )

            # Update slots according to the order of the participants in the list.
            slot_id0 = models.Participation.next_slot_id(self.object)
            for pidx, participant_name in enumerate(participant_names_list):
                participation = self.object.participations.get(participant__name = participant_name)
                participation.slot_id = slot_id0 + pidx
                participation.save()
            
            request.session['alert'] = dict(status = 'success', text = 'Attendees have been updated.')
        return redirect('manage-participants', pk = self.object.id)

    def get_context_data(self, **kwargs):
        context = super(ManageParticipantsView, self).get_context_data(**kwargs)
        context.update(VersionInfoMixin.get_context_data(self, **kwargs))
        context['breadcrumb'] = create_breadcrumb([
            dict(label = 'Index', url = reverse('index')),
            dict(label = self.object.name, url = self.request.path),
        ])
        context['participants'] = self.object.participations.all()
        return context


class TournamentProgressView(SingleObjectMixin, VersionInfoMixin, AlertMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Drafted tournaments cannot be started.
        if self.object.state == 'draft':
            return HttpResponse(status = 412)

        if self.object.state == 'open':

            # Tournament can only be started by the creator.
            if self.object.creator is not None and self.object.creator.id != request.user.id:
                return HttpResponseForbidden() 

            # Check whether there are at least 3 participants.
            if self.object.participations.count() < 3:
                return HttpResponse(status = 412)

            # Perform a test run.
            try:
                self.object.test()
            except ValidationError as error:
                request.session['alert'] = dict(status = 'danger', text = '\n'.join(error))
                return redirect('update-tournament', pk = self.object.id)

            # Change tournament state to "active".
            self.object.shuffle_participants()
            self.object.update_state()

        if self.object.state in ('active', 'finished'):
            return render(request, 'frontend/tournament-progress.html', self.get_context_data())

    def get_level_data(self, stage, level):
        return {
            'fixtures': [self.get_fixture_data(stage, level, fixture) for fixture in stage.fixtures.filter(level = level)],
            'name': stage.get_level_name(level),
        }

    def get_fixture_data(self, stage, level, fixture):
        return {
            'data': fixture,
            'editable': not fixture.is_confirmed and level == stage.current_level and self.request.user.id and stage.tournament.participations.filter(participant__user = self.request.user).count() > 0,
            'has_confirmed': fixture.confirmations.filter(id = self.request.user.id).count() > 0,
        }

    def get_context_data(self, **kwargs):
        context = super(TournamentProgressView, self).get_context_data(**kwargs)
        context.update(VersionInfoMixin.get_context_data(self, **kwargs))
        context['breadcrumb'] = create_breadcrumb([
            dict(label = 'Index', url = reverse('index')),
            dict(label = self.object.name, url = self.request.path),
        ])

        context['stages'] = dict()
        for stage_idx, stage in enumerate(self.object.stages.all()):
            context['stages'][stage.id] = dict(
                levels = [self.get_level_data(stage, level) for level in range(stage.levels)]
            )

            if self.object.current_stage and stage.id == self.object.current_stage.id:
                context['current_stage'] = stage_idx + 1

        if self.object.current_stage is None:
            context['current_stage'] = self.object.stages.count() + 1

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        fixture = models.Fixture.objects.get(id = request.POST.get('fixture_id'))

        # Check whether the user is a participator.
        if not request.user.id or self.object.participations.filter(participant__user = request.user).count() == 0:
            return HttpResponseForbidden() 

        # Check whether the tournament is active.
        if self.object.state != 'active':
            return HttpResponse(status = 412)

        # Check whether the fixture belongs to the currently active stage.
        if fixture.mode.id != self.object.current_stage.id:
            return HttpResponse(status = 412)

        # Check whether the fixture belongs to the current level.
        if fixture.level != self.object.current_stage.current_level:
            return HttpResponse(status = 412)

        # Check the score formatting.
        try:
            new_score = (int(request.POST.get('score1').strip()), int(request.POST.get('score2').strip()))
        except ValueError:
            request.session['alert'] = dict(status = 'danger', text = 'You have not entered a valid score.')
            return redirect('tournament-progress', pk = self.object.id)

        # Update the fixture.
        if fixture.score != new_score:

            # The score of an already fully confirmed fixture cannot be changed.
            if fixture.is_confirmed:
                return HttpResponse(status = 412)

            fixture.score = new_score

            try:
                fixture.full_clean()
            except ValidationError as error:
                request.session['alert'] = dict(status = 'danger', text = str(error))
                return redirect('tournament-progress', pk = self.object.id)

            fixture.save()
            fixture.confirmations.clear()

        # Add a confirmation.
        if fixture.confirmations.filter(id = request.user.id).count() == 0:
            fixture.confirmations.add(request.user)

        # Update the state of the tournament as soon as the fixture is fully confirmed.
        if fixture.is_confirmed:
            self.object.update_state()

        request.session['alert'] = dict(status = 'success', text = 'Your confirmation has been saved.')
        return redirect('tournament-progress', pk = self.object.id)


class CloneTournamentView(LoginRequiredMixin, SingleObjectMixin, View):

    model = models.Tournament

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        tournament = models.Tournament.load(
            definition = self.object.definition,
            name = self.object.name + ' (Copy)',
            creator = request.user)
        request.session['alert'] = dict(status = 'success', text = f'A copy of the tournament "{ self.object.name }" has been created (see below).')
        return redirect('update-tournament', pk = tournament.id)
