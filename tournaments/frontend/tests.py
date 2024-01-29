from django.urls import reverse
from django.test import TestCase

from . import views
from tournaments import models


password1 = 'Xz23#!sZ'


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
