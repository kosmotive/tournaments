from django import template

from tournaments.models import parse_participants_str_list


register = template.Library()


@register.filter
def get_type(value):
    return type(value).__name__


def position_to_str(pos):
    pos = str(int(pos))
    if pos.endswith('1'):
        return f'{pos}st'
    if pos.endswith('2'):
        return f'{pos}nd'
    if pos.endswith('3'):
        return f'{pos}rd'
    else:
        return f'{pos}th'


def slice_to_str(sl):
    return ', '.join((f'{position_to_str(item + 1)}' for item in range(sl.stop)[sl]))


@register.filter
def parse_participants(participants_str_list, tournament):
    participants = list()
    for identifier, placements_slice in parse_participants_str_list(participants_str_list):
        stage = tournament.stages.get(identifier = identifier)
        which = slice_to_str(placements_slice)
        if stage.name:
            stage_name = stage.name
        else:
            stage_position = [stage.id for stage in tournament.stages.all()].index(stage.id)
            stage_name = f'Tournament Stage {stage_position + 1}'
        participants.append(f'{which} of {stage_name}')
    return participants


@register.filter
def is_joined_by(tournament, user):
    return user.id is not None and tournament.participations.filter(user = user).count() > 0
