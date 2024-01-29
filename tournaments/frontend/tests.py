import re

from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse
from django.test import TestCase

from . import views
from tournaments import models
from tournaments.tests import test_tournament1_yml


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
        response = self.client.post(
            reverse('create-tournament'),
            dict(
                name = 'Test',
                definition = strip_yaml_indent(test_tournament1_yml),
            ),
            follow = True,
        )

        # Verify the response.
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.resolver_match.func.view_class, views.UpdateTournamentView)

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


def start_tournament(tournament):
    if not tournament.published:
        tournament.published = True
        tournament.save()
    users = [models.User.objects.create(username = f'user{idx}') for idx in range(10)]
    for user in users:
        models.Participation.objects.create(tournament = tournament, user = user, slot_id = models.Participation.next_slot_id(tournament))
    tournament.update_state()
    assert tournament.state == 'active'


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
        self.assertTrue(self.user1 in self.user2_tournament.participants)

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
        self.assertTrue(self.user1 in self.user1_tournament.participants)


class WithdrawTournamentViewTests(TestCase):

    def setUp(self):
        self.user1 = models.User.objects.create(username = 'test1')
        self.user2 = models.User.objects.create(username = 'test2')
        self.client.force_login(self.user1)

        self.user1_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test1', creator = self.user1, published = True)
        self.user2_tournament = models.Tournament.load(definition = test_tournament1_yml, name = 'Test2', creator = self.user2, published = True)

        for tournament in models.Participation.objects.all():
            for user in models.User.objects.all():
                models.Participation.objects.create(tournament = tournament, user = user, slot_id = models.Participation.next_slot_id(tournament))

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
