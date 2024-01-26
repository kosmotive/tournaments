import yaml
from django import forms
from django.core.exceptions import ValidationError

from tournaments import models


class CreateTournamentForm(forms.Form):

    name = forms.CharField(label = 'Name', max_length = 100, required = True)
    definition = forms.CharField(label = 'Definition', widget = forms.Textarea(attrs = {'class': 'textarea-monospace'}), required = True)

    def clean_definition(self):
        definition_str = self.cleaned_data['definition']
        try:
            definition = yaml.safe_load(definition_str)
            assert isinstance(definition, dict)
            return definition
        except:
            raise ValidationError('Definition must be supplied in valid YAML.')

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
