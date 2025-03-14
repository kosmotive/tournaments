import re

import yaml
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction

from tournaments import models


class SignupForm(UserCreationForm):

    def clean_username(self):
        ret = super(SignupForm, self).clean_username()
        if re.match(r'^testuser-[0-9]+$', self.cleaned_data.get('username')):
            raise ValidationError('This username is reserved.')
        return ret


class CreateTournamentForm(forms.Form):

    name = forms.CharField(label = 'Name', max_length = 100, required = True)
    definition = forms.CharField(label = 'Definition', widget = forms.Textarea(attrs = {'class': 'textarea-monospace'}), required = True)

    @transaction.atomic
    def validate_definition(self, definition):
        try:
            tournament = models.Tournament.load(definition = definition, name = 'Test')
            tournament.full_clean()
            for stage in tournament.stages.all():
                stage.full_clean()
        except ValidationError as error:
            raise ValidationError(' '.join((str(err) for err in error.messages))) from error
        except KeyError as error:
            raise ValidationError(f'Missing key: "{error.args[0]}".') from error
        except Exception as error:
            raise ValidationError(error) from error
        transaction.set_rollback(True)

    def clean_definition(self):
        definition_str = self.cleaned_data['definition']

        # Check for syntactic correctness.
        try:
            definition = yaml.safe_load(definition_str)
            assert isinstance(definition, dict)
        except (yaml.YAMLError, AssertionError) as error:
            raise ValidationError('Definition must be supplied in valid YAML.') from error

        # Check for semantic correctness.
        self.validate_definition(definition)

        return definition

    def create_tournament(self, request):
        tournament = models.Tournament.load(
            definition = self.cleaned_data['definition'],
            name = self.cleaned_data['name'],
            creator = request.user)
        tournament.definition = self.data['definition']
        tournament.save()
        return tournament


class UpdateTournamentForm(CreateTournamentForm):

    def update_tournament(self, request, tournament):
        tournament.delete()
        return self.create_tournament(request)
