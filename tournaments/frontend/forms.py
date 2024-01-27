import yaml
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from tournaments import models


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
            print(error)
            raise ValidationError(' '.join((str(err) for err in error.messages)))
        except KeyError as error:
            raise ValidationError(f'Missing key: "{error.args[0]}".')
        except Exception as error:
            raise ValidationError(error)
        transaction.set_rollback(True)

    def clean_definition(self):
        definition_str = self.cleaned_data['definition']

        # Check for syntactic correctness.
        try:
            definition = yaml.safe_load(definition_str)
            assert isinstance(definition, dict)
        except:
            raise ValidationError('Definition must be supplied in valid YAML.')

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
        tournament.stages.non_polymorphic().all().delete()
        tournament.delete()
        return self.create_tournament(request)
