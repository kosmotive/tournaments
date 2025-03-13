import re

from django.contrib.auth.views import LoginView
from django.urls import reverse
from django.test import TestCase

from . import views
from tournaments import models
from tournaments.tests import test_tournament1_yml, _confirm_fixture


password1 = 'Xz23#!sZ'


def strip_yaml_indent(yaml):
    lines = [line for line in yaml.split('\n') if len(line) > 0]
    indent = min((len(re.match(r'^([ ]*)', line).group(1)) for line in lines))
    return '\n'.join((line[indent:] for line in lines))


class IndexViewTests(TestCase):

    def test_empty(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Create Tournament')
        self.assertNotContains(response, 'All Stars')
        self.assertNotContains(response, 'Active')
        self.assertNotContains(response, 'Your Drafts')
        self.assertNotContains(response, 'Open')
        self.assertNotContains(response, 'Finished')

    def test_authenticated_empty(self):
        user = models.User.objects.create(username = 'test1')
        self.client.force_login(user)

        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Tournament')
        self.assertNotContains(response, 'All Stars')
        self.assertNotContains(response, 'Active')
        self.assertNotContains(response, 'Your Drafts')
        self.assertNotContains(response, 'Open')
        self.assertNotContains(response, 'Finished')

    def test_authenticated_draft_of_other_user(self):
        tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test')
        self.test_authenticated_empty()

    def test_authenticated_draft(self):
        user = models.User.objects.create(username = 'test1')
        self.client.force_login(user)

        tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test', creator = user)

        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Tournament')
        self.assertNotContains(response, 'All Stars')
        self.assertNotContains(response, 'Active')
        self.assertContains(response, 'Your Drafts')
        self.assertNotContains(response, 'Open')
        self.assertNotContains(response, 'Finished')

        self.assertContains(response, 'Preliminaries')
        self.assertContains(response, 'Main Round')
        self.assertContains(response, 'Match for 3rd Place')
        self.assertContains(response, 'Podium')
        self.assertContains(response, 'Edit')


class SignupViewTests(TestCase):

    def test_form(self):

        # Verify the signup form.
        response = self.client.get(reverse('signup'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Username')
        self.assertContains(response, 'Password')
        self.assertContains(response, 'Password confirmation')

    def test_post(self):

        # Submit the signup form (correctly).
        response = self.client.post(reverse('signup'),
            dict(
                username  = 'user1',
                password1 = password1,
                password2 = password1),
            follow = True,
        )

        # Verify that a user was created.
        self.assertTrue(models.User.objects.filter(username = 'user1').count() == 1)

        # Verify that the user is logged in.
        self.assertIsNotNone(response.context['user'].id)

        # Verify that the user is redirected to the index.
        self.assertIs(response.resolver_match.func.view_class, views.IndexView)

    def test_post_different_passwords(self):

        # Submit the signup form (incorrectly).
        response = self.client.post(reverse('signup'), dict(
            username  = 'user1',
            password1 = password1,
            password2 = password1[::-1],
        ))

        # Verify the signup form and the error.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Username')
        self.assertContains(response, 'Password')
        self.assertContains(response, 'Password confirmation')
        self.assertContains(response, 'There have been issues with your input. Please see below and try again.')
        self.assertContains(response, 'The two password fields didn’t match.')

    def test_post_forbidden_username(self):

        # Submit the signup form (incorrectly).
        response = self.client.post(reverse('signup'), dict(
            username  = 'testuser-2',
            password1 = password1,
            password2 = password1,
        ))

        # Verify the signup form and the error.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Username')
        self.assertContains(response, 'Password')
        self.assertContains(response, 'Password confirmation')
        self.assertContains(response, 'There have been issues with your input. Please see below and try again.')
        self.assertContains(response, 'This username is reserved.')


class CreateTournamentViewTests(TestCase):

    def setUp(self):
        user = models.User.objects.create(username = 'test1')
        self.client.force_login(user)

    def test_unauthenticated(self):
        self.client.logout()

        response = self.client.get(reverse('create-tournament'), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

        response = self.client.post(reverse('create-tournament'), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

    def test_form(self):

        # Verify the form.
        response = self.client.get(reverse('create-tournament'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Tournament')
        self.assertContains(response, 'Name')
        self.assertContains(response, 'Definition')
        self.assertContains(response, 'Preview')

    def test_post(self):

        # Submit the form.
        definition = strip_yaml_indent(test_tournament1_yml)
        response = self.client.post(
            reverse('create-tournament'),
            dict(
                name = 'Test',
                definition = definition,
            ),
            follow = True,
        )

        # Verify the response.
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertContains(response, definition)

    def test_post_illegal_yaml(self):

        # Submit the form.
        response = self.client.post(reverse('create-tournament'), dict(
            name = 'Test',
            definition = '1 + 1',
        ))

        # Verify the form and the error.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Tournament')
        self.assertContains(response, 'Name')
        self.assertContains(response, 'Definition')
        self.assertContains(response, 'Preview')
        self.assertContains(response, 'Definition must be supplied in valid YAML.')


class UpdateTournamentViewTests(TestCase):

    def setUp(self):
        user1 = models.User.objects.create(username = 'test1')
        user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(user1)

        self.user1_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = user1)
        self.user2_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = user2)

    def test_unauthenticated(self):
        self.client.logout()

        response = self.client.get(reverse('update-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

        response = self.client.post(reverse('update-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

    def test_not_found(self):
        response = self.client.get(reverse('update-tournament', kwargs = dict(pk = 0)))
        self.assertEqual(response.status_code, 404)

    def test_foreign(self):
        response = self.client.get(reverse('update-tournament', kwargs = dict(pk = self.user2_tournament.id)))
        self.assertEqual(response.status_code, 403)

        self.user2_tournament.creator = None
        self.user2_tournament.save()

        response = self.client.get(reverse('update-tournament', kwargs = dict(pk = self.user2_tournament.id)))
        self.assertEqual(response.status_code, 403)

    def test_published(self):
        self.user1_tournament.published = True
        self.user1_tournament.save()
        response = self.client.post(reverse('update-tournament', kwargs = dict(pk = self.user1_tournament.id)))
        self.assertEqual(response.status_code, 412)

    def test(self):
        response = self.client.get(reverse('update-tournament', kwargs = dict(pk = self.user1_tournament.id)))
        self.assertEqual(response.status_code, 200)

        # Verify the form.
        self.assertContains(response, 'Name')
        self.assertContains(response, 'Test1')
        self.assertContains(response, 'Definition')
        self.assertContains(response, 'Preview')

        # Verify preview.
        self.assertContains(response, 'Preliminaries')
        self.assertContains(response, 'Main Round')
        self.assertContains(response, 'Match for 3rd Place')
        self.assertContains(response, 'Podium')
        self.assertContains(response, 'Delete')
        self.assertContains(response, 'Publish')

    def test_post(self):

        # Submit the form.
        response = self.client.post(
            reverse('update-tournament', kwargs = dict(pk = self.user1_tournament.id)),
            dict(
                name = 'Test1 updated',
                definition = strip_yaml_indent(test_tournament1_yml),
            ),
            follow = True,
        )

        # Verify the response.
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertContains(response, 'Test1 updated')

        # Verify that the tournament is re-created.
        self.assertTrue(models.Tournament.objects.filter(name = 'Test1 updated').count() > 0)
        self.assertTrue(models.Tournament.objects.filter(id = self.user1_tournament.id).count() == 0)


class PublishTournamentViewTests(TestCase):

    def setUp(self):
        user1 = models.User.objects.create(username = 'test1')
        user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(user1)

        self.user1_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = user1)
        self.user2_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = user2)

    def test_unauthenticated(self):
        self.client.logout()

        response = self.client.get(reverse('publish-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

    def test_not_found(self):
        response = self.client.get(reverse('publish-tournament', kwargs = dict(pk = 0)))
        self.assertEqual(response.status_code, 404)

    def test_foreign(self):
        response = self.client.get(reverse('publish-tournament', kwargs = dict(pk = self.user2_tournament.id)))
        self.assertEqual(response.status_code, 403)

        self.user2_tournament.creator = None
        self.user2_tournament.save()

        response = self.client.get(reverse('publish-tournament', kwargs = dict(pk = self.user2_tournament.id)))
        self.assertEqual(response.status_code, 403)

    def test_published(self):
        self.user1_tournament.published = True
        self.user1_tournament.save()
        response = self.client.get(reverse('publish-tournament', kwargs = dict(pk = self.user1_tournament.id)))
        self.assertEqual(response.status_code, 412)

    def test(self):
        response = self.client.get(reverse('publish-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.user1_tournament.refresh_from_db()
        self.assertTrue(self.user1_tournament.published)


def add_participants(tournament, num_users = 10, names = list()):
    if not tournament.published:
        tournament.published = True
        tournament.save()
    users = [models.User.objects.get_or_create(username = f'user{idx}')[0] for idx in range(num_users)]
    for user in users:
        participant = models.Participant.get_or_create_for_user(user)
        models.Participation.objects.create(tournament = tournament, participant = participant, slot_id = models.Participation.next_slot_id(tournament))
    for name in names:
        participant = models.Participant.objects.get_or_create(name = name)[0]
        models.Participation.objects.create(tournament = tournament, participant = participant, slot_id = models.Participation.next_slot_id(tournament))
    return users


def start_tournament(tournament, **kwargs):
    users = add_participants(tournament, **kwargs)
    tournament.update_state()
    assert tournament.state == 'active'
    return users


class DraftTournamentViewTests(TestCase):

    def setUp(self):
        user1 = models.User.objects.create(username = 'test1')
        user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(user1)

        self.user1_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = user1, published = True)
        self.user2_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = user2, published = True)

    def test_unauthenticated(self):
        self.client.logout()

        response = self.client.get(reverse('draft-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

    def test_not_found(self):
        response = self.client.get(reverse('draft-tournament', kwargs = dict(pk = 0)))
        self.assertEqual(response.status_code, 404)

    def test_foreign(self):
        response = self.client.get(reverse('draft-tournament', kwargs = dict(pk = self.user2_tournament.id)))
        self.assertEqual(response.status_code, 403)

        self.user2_tournament.creator = None
        self.user2_tournament.save()

        response = self.client.get(reverse('draft-tournament', kwargs = dict(pk = self.user2_tournament.id)))
        self.assertEqual(response.status_code, 403)

    def test_drafted(self):
        self.user1_tournament.published = False
        self.user1_tournament.save()
        response = self.client.get(reverse('draft-tournament', kwargs = dict(pk = self.user1_tournament.id)))
        self.assertEqual(response.status_code, 412)

    def test_active(self):
        start_tournament(self.user1_tournament)
        response = self.client.get(reverse('draft-tournament', kwargs = dict(pk = self.user1_tournament.id)))
        self.assertEqual(response.status_code, 412)

    def test(self):
        response = self.client.get(reverse('draft-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.user1_tournament.refresh_from_db()
        self.assertFalse(self.user1_tournament.published)


class DeleteTournamentViewTests(TestCase):

    def setUp(self):
        user1 = models.User.objects.create(username = 'test1')
        user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(user1)

        self.user1_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = user1)
        self.user2_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = user2)

    def test_unauthenticated(self):
        self.client.logout()

        response = self.client.get(reverse('delete-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

    def test_not_found(self):
        response = self.client.get(reverse('delete-tournament', kwargs = dict(pk = 0)))
        self.assertEqual(response.status_code, 404)

    def test_foreign(self):
        response = self.client.get(reverse('delete-tournament', kwargs = dict(pk = self.user2_tournament.id)))
        self.assertEqual(response.status_code, 403)

        self.user2_tournament.creator = None
        self.user2_tournament.save()

        response = self.client.get(reverse('delete-tournament', kwargs = dict(pk = self.user2_tournament.id)))
        self.assertEqual(response.status_code, 403)

    def test_published(self):
        self.user1_tournament.published = True
        self.user1_tournament.save()
        response = self.client.get(reverse('delete-tournament', kwargs = dict(pk = self.user1_tournament.id)))
        self.assertEqual(response.status_code, 412)

    def test_active(self):
        start_tournament(self.user1_tournament)
        response = self.client.get(reverse('delete-tournament', kwargs = dict(pk = self.user1_tournament.id)))
        self.assertEqual(response.status_code, 412)

    def test(self):
        response = self.client.get(reverse('delete-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.IndexView)
        self.assertTrue(models.Tournament.objects.filter(id = self.user1_tournament.id).count() == 0)


class JoinTournamentViewTests(TestCase):

    def setUp(self):
        self.user1 = models.User.objects.create(username = 'test1')
        self.user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(self.user1)

        self.user1_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = self.user1, published = True)
        self.user2_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = self.user2, published = True)

    def test_unauthenticated(self):
        self.client.logout()

        response = self.client.get(reverse('join-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

    def test_not_found(self):
        response = self.client.get(reverse('join-tournament', kwargs = dict(pk = 0)))
        self.assertEqual(response.status_code, 404)

    def test_foreign(self):
        response = self.client.get(reverse('join-tournament', kwargs = dict(pk = self.user2_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertTrue(self.user1 in self.user2_tournament.participating_users)

    def test_drafted(self):
        self.user1_tournament.published = False
        self.user1_tournament.save()
        response = self.client.get(reverse('join-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 412)

    def test_active(self):
        start_tournament(self.user1_tournament)
        response = self.client.get(reverse('join-tournament', kwargs = dict(pk = self.user1_tournament.id)))
        self.assertEqual(response.status_code, 412)

    def test_joined(self):
        self.test()
        self.test()

    def test(self):
        response = self.client.get(reverse('join-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertTrue(self.user1 in self.user1_tournament.participating_users)


class WithdrawTournamentViewTests(TestCase):

    def setUp(self):
        self.user1 = models.User.objects.create(username = 'test1')
        self.user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(self.user1)

        self.user1_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = self.user1, published = True)
        self.user2_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = self.user2, published = True)

        for tournament in models.Participation.objects.all():
            for user in models.User.objects.all():
                models.Participation.objects.create(tournament = tournament, participant = models.Participant.create_for_user(user), slot_id = models.Participation.next_slot_id(tournament))

    def test_unauthenticated(self):
        self.client.logout()

        response = self.client.get(reverse('withdraw-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

    def test_not_found(self):
        response = self.client.get(reverse('withdraw-tournament', kwargs = dict(pk = 0)))
        self.assertEqual(response.status_code, 404)

    def test_foreign(self):
        response = self.client.get(reverse('withdraw-tournament', kwargs = dict(pk = self.user2_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertFalse(self.user1 in self.user2_tournament.participants)

    def test_drafted(self):
        self.user1_tournament.published = False
        self.user1_tournament.save()
        response = self.client.get(reverse('withdraw-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 412)

    def test_active(self):
        start_tournament(self.user1_tournament)
        response = self.client.get(reverse('withdraw-tournament', kwargs = dict(pk = self.user1_tournament.id)))
        self.assertEqual(response.status_code, 412)

    def test_withdrawn(self):
        self.test()
        self.test()

    def test(self):
        response = self.client.get(reverse('withdraw-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertFalse(self.user1 in self.user1_tournament.participants)


class CloneTournamentViewTests(TestCase):

    def setUp(self):
        self.user1 = models.User.objects.create(username = 'test1')
        self.user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(self.user1)

        self.user1_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = self.user1, published = True)
        self.user2_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = self.user2, published = True)

    def test_unauthenticated(self):
        self.client.logout()

        response = self.client.get(reverse('clone-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, LoginView)

    def test_not_found(self):
        response = self.client.get(reverse('clone-tournament', kwargs = dict(pk = 0)))
        self.assertEqual(response.status_code, 404)

    def test_foreign(self):
        response = self.client.get(reverse('clone-tournament', kwargs = dict(pk = self.user2_tournament.id)), follow = True)
        clone = models.Tournament.objects.get(name = 'Test2 (Copy)')
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertEqual(clone.definition, self.user1_tournament.definition)
        self.assertEqual(clone.creator.id, self.user1.id)

    def test_drafted(self):
        self.user1_tournament.published = False
        self.user1_tournament.save()
        response = self.client.get(reverse('clone-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        clone = models.Tournament.objects.get(name = 'Test1 (Copy)')
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertEqual(clone.definition, self.user1_tournament.definition)
        self.assertEqual(clone.creator.id, self.user1.id)

    def test_active(self):
        start_tournament(self.user1_tournament)
        response = self.client.get(reverse('clone-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        clone = models.Tournament.objects.get(name = 'Test1 (Copy)')
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertEqual(clone.definition, self.user1_tournament.definition)
        self.assertEqual(clone.creator.id, self.user1.id)

    def test(self):
        response = self.client.get(reverse('clone-tournament', kwargs = dict(pk = self.user1_tournament.id)), follow = True)
        clone = models.Tournament.objects.get(name = 'Test1 (Copy)')
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertEqual(clone.definition, self.user1_tournament.definition)


class TournamentProgressViewTests(TestCase):

    def setUp(self):
        self.user1 = models.User.objects.create(username = 'test1')
        self.user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(self.user1)

        self.tournament1 = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = self.user1, published = True)
        self.tournament2 = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = self.user2, published = True)

        self.users = add_participants(self.tournament1, users = 10)

    def test_unauthenticated_open(self):
        """
        Starting a tournament as an authenticated user yields 403 (forbidden).
        """
        self.client.logout()

        response = self.client.get(reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)))
        self.assertEqual(response.status_code, 403)

    def test_foreign_open(self):
        """
        Starting a tournament created by a different user yields 403 (forbidden).
        """
        response = self.client.get(reverse('tournament-progress', kwargs = dict(pk = self.tournament2.id)))
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_active(self):
        self.test_open()
        self.client.logout()

        response = self.client.get(reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<h2>Preliminaries <small class="text-muted">Current Stage</small></h2>')

    def test_not_found(self):
        response = self.client.get(reverse('tournament-progress', kwargs = dict(pk = 0)))
        self.assertEqual(response.status_code, 404)

    def test_drafted(self):
        self.tournament1.published = False
        self.tournament1.save()
        response = self.client.get(reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)))
        self.assertEqual(response.status_code, 412)

    def test_less_than_3_participators(self):
        """
        Starting a tournament created by the user yields 412 (precondition failed) if there are fewer than 3 participators.
        """
        self.client.force_login(self.user2)
        add_participants(self.tournament2, users = 2)
        response = self.client.get(reverse('tournament-progress', kwargs = dict(pk = self.tournament2.id)))
        self.assertEqual(response.status_code, 412)

    def test_less_than_5_participators(self):
        """
        Starting a tournament created by the user fails if `Tournament.test` checking fails.
        """
        self.client.force_login(self.user2)
        add_participants(self.tournament2, users = 4)
        response = self.client.get(reverse('tournament-progress', kwargs = dict(pk = self.tournament2.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertContains(response, 'insufficient participants: main_round[2] is out of range')

    def test_less_than_6_participators(self):
        """
        Starting a tournament created by the user fails if `Tournament.test` checking fails.
        """
        self.client.force_login(self.user2)
        add_participants(self.tournament2, users = 5)
        response = self.client.get(reverse('tournament-progress', kwargs = dict(pk = self.tournament2.id)), follow = True)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)
        self.assertContains(response, 'Error while initializing tournament (insufficient participants).')

    def test_open(self):
        """
        Successfulls starts an open tournament.
        """
        response = self.client.get(reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.tournament1.state, 'active')
        self.assertContains(response, '<h2>Preliminaries <small class="text-muted">Current Stage</small></h2>')

    def test_post_open(self):
        fixture = models.Fixture.objects.create(mode = self.tournament1.stages.all()[0], level = 0)
        response = self.client.post(
            reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)),
            dict(
                fixture_id = fixture.id,
                score1 = '10',
                score2 = '12',
            ),
        )
        self.assertEqual(response.status_code, 403)

    def test_post_not_participating(self):
        self.test_open() ## start the tournament
        fixture = self.tournament1.current_stage.fixtures.filter(level = self.tournament1.current_stage.current_level)[0]
        response = self.client.post(
            reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)),
            dict(
                fixture_id = fixture.id,
                score1 = '10',
                score2 = '12',
            ),
        )
        self.assertEqual(response.status_code, 403)

    def test_post_wrong_level(self):
        self.test_open() ## start the tournament
        self.client.force_login(self.users[0])
        fixture = self.tournament1.current_stage.fixtures.filter(level = self.tournament1.current_stage.current_level + 1)[0]
        response = self.client.post(
            reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)),
            dict(
                fixture_id = fixture.id,
                score1 = '10',
                score2 = '12',
            ),
        )
        self.assertEqual(response.status_code, 412)

    def test_post_wrong_stage(self):
        self.test_open() ## start the tournament
        self.client.force_login(self.users[0])
        next_stage = self.tournament1.stages.all()[1]
        fixture = models.Fixture.objects.create(mode = next_stage, level = 0)
        response = self.client.post(
            reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)),
            dict(
                fixture_id = fixture.id,
                score1 = '10',
                score2 = '12',
            ),
        )
        self.assertEqual(response.status_code, 412)

    def test_post_already_confirmed(self):
        self.test_open() ## start the tournament
        self.client.force_login(self.users[0])
        fixture = self.tournament1.current_stage.fixtures.filter(level = self.tournament1.current_stage.current_level)[0]
        _confirm_fixture(self.tournament1.participating_users, fixture)
        response = self.client.post(
            reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)),
            dict(
                fixture_id = fixture.id,
                score1 = '10',
                score2 = '12',
            ),
            follow = True
        )
        self.assertEqual(response.status_code, 412)

    def test_post_invalid_score(self):
        self.test_open() ## start the tournament
        self.client.force_login(self.users[0])
        fixture = self.tournament1.current_stage.fixtures.filter(level = self.tournament1.current_stage.current_level)[0]
        response = self.client.post(
            reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)),
            dict(
                fixture_id = fixture.id,
                score1 = '',
                score2 = '12',
            ),
            follow = True
        )
        fixture.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fixture.score, (None, None))
        self.assertContains(response, 'You have not entered a valid score.')

    def test_post(self):
        self.test_open() ## start the tournament
        self.client.force_login(self.users[0])
        fixture = self.tournament1.current_stage.fixtures.filter(level = self.tournament1.current_stage.current_level)[0]
        response = self.client.post(
            reverse('tournament-progress', kwargs = dict(pk = self.tournament1.id)),
            dict(
                fixture_id = fixture.id,
                score1 = '10',
                score2 = '12',
            ),
            follow = True
        )
        fixture.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fixture.score, (10, 12))
        self.assertContains(response, 'Your confirmation has been saved.')
        self.assertContains(response, 'Confirmations: 1 / 6')
        self.assertContains(response, 'You have confirmed.')


class ManageParticipantsViewTests(TestCase):

    def setUp(self):
        self.user1 = models.User.objects.create(username = 'test1')
        self.user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(self.user1)

        self.tournament1 = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = self.user1, published = True)
        self.tournament2 = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = self.user1, published = True)

    def test_get(self):
        add_participants(self.tournament1, num_users = 3, names = ['Participant1'])
        response = self.client.get(reverse('manage-participants', kwargs = dict(pk = self.tournament1.id)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Manage Attendees')
        self.assertContains(response, 'Attendee Names (one per line)')
        self.assertContains(response, 'Save Attendees')
        self.assertContains(response, '\n'.join(f'user{i}' for i in range(3)) + '\n' + 'Participant1')

    def test_post(self):
        add_participants(self.tournament1, num_users = 3, names = ['Participant1', 'Participant2', 'Participant3'])
        add_participants(self.tournament2, names = ['Participant3'])

        # Submit updated list of participant names.
        participant_names_expected = ['user1', 'Participant1', 'Participant4', 'user2']
        participant_names_text = '\n'.join(participant_names_expected)
        response = self.client.post(reverse('manage-participants', kwargs = dict(pk = self.tournament1.id)),
                                    dict(participant_names = participant_names_text), follow = True)
        
        # Check that the submission was successful.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Attendees have been updated.')

        # Check that `Participant1` and `Participant3` still exist, and `Participant4` has been created.
        for i in [1, 3, 4]:
            self.assertTrue(models.Participant.objects.filter(name = f'Participant{i}').exists(), f'Participant{i} does not exist.')

        # Check that `Participant2` has been deleted.
        self.assertFalse(models.Participant.objects.filter(name = f'Participant2').exists())

        # Check that the right, and only the right participants are participating.
        participant_names_actual = [participation.participant.name for participation in self.tournament1.participations.all()]
        self.assertEqual(participant_names_actual, participant_names_expected)
