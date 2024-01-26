from django import template

from tournaments.models import parse_participants_str_list


register = template.Library()


@register.filter
def get_type(value):
    return type(value).__name__


def slice_to_str(sl):
    return ', '.join((f'{item + 1}.' for item in range(sl.stop)[sl]))


@register.filter
def parse_participants(participants_str_list, tournament):
    participants = list()
    for identifier, placements_slice in parse_participants_str_list(participants_str_list):
        stage = tournament.stages.get(identifier = identifier)
        which = slice_to_str(placements_slice)
        participants.append(f'{which} of {stage.name}')
    print(participants)
    return participants
