import math
import re
import random

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import CheckConstraint, Q, Min, Max
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from polymorphic.models import PolymorphicModel

import numpy as np


class Tournament(models.Model):

    name = models.CharField(blank = False, max_length = 100)
    definition = models.TextField(null = True, blank = True)
    podium_spec = models.JSONField()
    published = models.BooleanField(default = False)
    creator = models.ForeignKey('auth.User', on_delete = models.SET_NULL, related_name = 'tournaments', null = True, blank = True)

    @staticmethod
    def load(definition, name, **kwargs):
        if isinstance(definition, str):
            import yaml
            definition_str = definition
            definition = yaml.safe_load(definition)
        else:
            definition_str = None

        assert isinstance(definition, dict), repr(definition)
        if len(definition['podium']) == 0:
            raise ValidationError('No podium definition given.')

        tournament = Tournament.objects.create(name = name, podium_spec = definition['podium'], definition = definition_str, **kwargs)

        for stage in definition['stages']:
            stage = {key.replace('-', '_'): value for key, value in stage.items()}
            stage['tournament'] = tournament

            if 'id' in stage.keys( ):
                stage['identifier'] = stage.pop('id')

            mode_type = stage.pop('mode')

            if mode_type == 'groups':
                mode = Groups.objects.create(**stage)

            elif mode_type == 'knockout':
                mode = Knockout.objects.create(**stage)

            elif mode_type == 'division':
                stage['min_group_size'] = 2
                stage['max_group_size'] = 32767 ## https://docs.djangoproject.com/en/5.0/ref/models/fields/#positivesmallintegerfield
                mode = Groups.objects.create(**stage)

            else:
                raise ValidationError(f'Unknown mode: "{mode_type}".')

        return tournament

    @property
    def participants(self):
        return User.objects.filter(participations__tournament = self).order_by('participations__slot_id')

    @property
    def current_stage(self):
        for stage in self.stages.all():
            if not stage.is_finished:
                return stage
        return None ## indicates that the tournament is finished

    @transaction.atomic
    def shuffle_participants(self):
        count = self.participations.count()
        if count == 0: return ## early out, so that min/max operations below are well defined
        new_slot_ids = list(range(count))
        random.shuffle(new_slot_ids)

        # SQLite does not support deferred unique constraints, therefore we need to work around.
        min_slot_id = self.participations.aggregate(Min('slot_id'))['slot_id__min']
        max_slot_id = self.participations.aggregate(Max('slot_id'))['slot_id__max']

        # If any value of `new_slot_ids` is already taken, add an offset to establish uniqueness.
        if min_slot_id < count:
            for new_slot_id, participation in zip(new_slot_ids, self.participations.all()):
                participation.slot_id = max_slot_id + 1 + new_slot_id
                participation.save()

        # Otherwise, the values of `new_slot_ids` can be assigned directly.
        else:
            for new_slot_id, participation in zip(new_slot_ids, self.participations.all()):
                participation.slot_id = new_slot_id
                participation.save()

    def update_state(self):
        if self.current_stage is None:

            # If the tournament is finished, update the podium positions.
            podium = self._get_podium()
            for position, participant in enumerate(podium):
                participation = self.participations.get(user = participant)
                participation.podium_position = position
                participation.save()

        else:

            # Propagate `update_state` to the current stage as long as updates happen.
            while self.current_stage.update_state():
                pass

    @property
    def state(self):
        if not self.published:
            return 'draft'
        if Fixture.objects.filter(mode__tournament = self).count() == 0:
            return 'open'
        if self.current_stage is not None:
            return 'active'
        else:
            return 'finished'

    @property
    def podium(self):
        return User.objects.filter(participations__tournament = self, participations__podium_position__isnull = False).order_by('participations__podium_position')

    def _get_podium(self):
        podium = list()
        for identifier, position in parse_participants_str_list(self.podium_spec):

            try:
                podium_chunk = unwrap_list(self.stages.get(identifier = identifier).placements[position])
            except IndexError:
                raise ValueError(f'insufficient participants: {identifier}[{position}] is out of range')

            if isinstance(podium_chunk, list):
                podium += podium_chunk
            else:
                podium.append(podium_chunk)
        return podium

    def clean(self):
        super(Tournament, self).clean()
        try:
            for identifier, position in parse_participants_str_list(self.podium_spec):
                try:
                    self.stages.get(identifier = identifier)
                except Mode.DoesNotExist:
                    raise ValueError(f'stage "{identifier}" does not exist')
        except Exception as error:
            raise ValidationError(f'Error parsing "podium" definition ({error}).')

    @transaction.atomic
    def test(self):
        tournament = Tournament.load(definition = self.definition, name = 'Test')
        for participant in (User.objects.create(username = f'testuser-{pidx}', password = 'password') for pidx in range(len(self.participants))):
            Participation.objects.create(user = participant, tournament = tournament, slot_id = Participation.next_slot_id(tournament))

        # Initialize the tournament.
        try:
            tournament.update_state()
        except Exception as error:
            raise ValidationError(f'Error while initializing tournament ({error}).')

        # Play through the tournament, always make the participant with the higher ID win.
        while tournament.current_stage is not None:

            assert tournament.current_stage.fixtures.count() > 0
            try:

                # Play the current level, then update the tournament state.
                for fixture in tournament.current_stage.current_fixtures:

                    for participant in tournament.participants[:fixture.required_confirmations_count]:
                        fixture.confirmations.add(participant)

                    fixture.score = (fixture.player1.id, fixture.player2.id)
                    fixture.save()

                tournament.update_state()

            except Exception as error:
                if tournament.current_stage is None:
                    raise ValidationError(f'Error while validating podium ({error}).')
                else:
                    raise ValidationError(f'Error while validating "{tournament.current_stage.identifier}" stage ({error}).')

        transaction.set_rollback(True)

    def __str__(self):
        return self.name


@receiver(pre_delete, sender=Tournament)
def delete_tournament_stages(sender, instance, **kwargs):
    instance.stages.non_polymorphic().all().delete()


class Participation(models.Model):

    user = models.ForeignKey('auth.User', on_delete = models.PROTECT, related_name = 'participations')
    tournament = models.ForeignKey('Tournament', on_delete = models.CASCADE, related_name = 'participations')
    slot_id = models.PositiveIntegerField()
    podium_position = models.PositiveIntegerField(null = True, blank = True)

    @staticmethod
    def next_slot_id(tournament):
        return Participation.objects.filter(tournament = tournament).aggregate(Max('slot_id', default = -1))['slot_id__max'] + 1

    class Meta:
        ordering = ('tournament', 'slot_id')
        unique_together = [
            ('tournament', 'slot_id'),
            ('tournament', 'user'),
            ('tournament', 'podium_position'),
        ]


def parse_participants_str_list(participants_str_list):
    participants = [parse_placements_str(participants_str) for participants_str in participants_str_list]

    # Convert list of (identifier, slice) pairs into list of (identifier, position) pairs.
    references = list()
    for identifier, placements_slice in participants:
        for position in range(placements_slice.stop)[placements_slice]:
            references.append((identifier, position))

    # Verify that the list of participants is disjoint.
    if len(references) > len(frozenset(references)):
        raise ValueError(f'list of participants is not disjoint')

    return references


def parse_placements_str(placement_str):
    try:
        m = re.match(r'^([a-zA-Z_0-9]+)\.placements\[([-0-9:]+)\]$', placement_str)
        identifier = m.group(1)
        slice_str = m.group(2)
        parts = slice_str.split(':')
        parts = [int(part) if len(part) > 0 else None for part in parts]
        assert 1 <= len(parts) <= 3, slice_str
        if len(parts) == 1: parts = parts + [parts[0] + 1]
        placements_slice = slice(*parts)
        return identifier, placements_slice
    except Exception as error:
        raise ValueError(f'cannot parse placement: "{placement_str}"')


def unwrap_list(items):
    if isinstance(items, list):
        return unwrap_list(items[0]) if len(items) == 1 else items
    else:
        return items


class Mode(PolymorphicModel):

    identifier = models.SlugField()
    name = models.CharField(max_length = 100, blank = True)
    tournament = models.ForeignKey('Tournament', on_delete = models.CASCADE, related_name = 'stages')
    played_by  = models.JSONField(default = list, blank = True)

    def clean(self):
        super(Mode, self).clean()
        try:
            for identifier, position in parse_participants_str_list(self.played_by):
                try:
                    self.tournament.stages.get(identifier = identifier)
                except Mode.DoesNotExist:
                    raise ValueError(f'stage "{identifier}" does not exist')
        except Exception as error:
            raise ValidationError(f'Error parsing "played_by" definition of "{self.identifier}" stage ({error}).')

    def create_fixtures(self, participants):
        raise NotImplementedError()

    @property
    def placements(self):
        raise NotImplementedError()

    def update_state(self):
        if self.fixtures.count() == 0:
            participants = self.participants
            self.create_fixtures(participants)
            return True
        else:
            return self.update_fixtures()

    @property
    def participants(self):
        if len(self.played_by) == 0:
            return self.tournament.participants
        participants = list()
        for identifier, position in parse_participants_str_list(self.played_by):

            try:
                participants_chunk = unwrap_list(self.tournament.stages.get(identifier = identifier).placements[position])
            except IndexError:
                raise ValueError(f'insufficient participants: {identifier}[{position}] is out of range')

            if isinstance(participants_chunk, list):
                participants += participants_chunk
            else:
                participants.append(participants_chunk)
        return participants

    @property
    def levels(self):
        if self.fixtures.count() == 0:
            return 0
        else:
            return 1 + self.fixtures.aggregate(Max('level'))['level__max']

    @property
    def current_level(self):
        for level in range(self.levels):
            fixtures = self.fixtures.filter(level = level)
            if not all((fixture.is_confirmed for fixture in fixtures)):
                return level
        return self.levels

    def get_level_name(self, level):
        return None

    @property
    def current_fixtures(self):
        if self.is_finished:
            return None
        else:
            return self.fixtures.filter(level = self.current_level)

    @property
    def is_finished(self):
        if self.levels == 0:
            return False
        else:
            return self.current_level == self.levels

    def check_fixture(self, fixture):
        pass

    def update_fixtures(self):
        return False

    def __str__(self):
        return self.identifier


def split_into_groups(items, min_group_size, max_group_size):
    """
    Split items into approximately evenly sized groups.
    """
    assert min_group_size >= 1
    assert max_group_size >= min_group_size

    # Assign items to approximately evenly sized groups.
    groups = [list() for _ in range(math.ceil(len(items) / max_group_size))]
    next_group_idx = 0
    for item in items:
        groups[next_group_idx].append(item)
        next_group_idx = (next_group_idx + 1) % len(groups)

    # Retain only non-empty groups.
    groups = [group for group in groups if len(group) > 0]

    # Check `min_group_size` constraint.
    if any((len(group) < min_group_size for group in groups)):
        raise ValueError('insufficient participants')

    return groups


def create_division_schedule(participants, with_returns = False):
    """
    Return list of match days, where each match day is a list of pairings of the participants (tuples).

    See https://en.wikipedia.org/wiki/Round-robin_tournament
    """
    if len(participants) % 2 == 1:
        plist = np.arange(len(participants) + 1)
        schedule = list()
        for pairings in create_division_schedule(plist, with_returns = with_returns):
            schedule.append([(participants[p1], participants[p2]) for p1, p2 in pairings if p1 < len(participants) and p2 < len(participants)])
        return schedule
    else:
        if with_returns:
            schedule = create_division_schedule(participants, with_returns = False)
            return schedule + [[(p2, p1) for p1, p2 in matchday] for matchday in schedule]
        else:
            n = len(participants)
            schedule = list()
            for level in range(n - 1):
                pairings = [(participants[level], participants[n - 1])]
                if level % 2 == 1:
                    pairings[0] = pairings[0][::-1]
                for step in range(1, n // 2):
                    pidx1 = (step + level) % (n - 1)
                    pidx2 = (n - 1 - step + level) % (n - 1)
                    pairing = (participants[pidx1], participants[pidx2])
                    pairings.append(pairing if step % 2 == 0 else pairing[::-1])
                schedule.append(pairings)
            return schedule


def get_stats(participant, filters = dict()):
    row = dict(participant = participant, win_count = 0, loss_count = 0, draw_count = 0, matches = 0)
    for fixture in participant.fixtures1.filter(**filters) | participant.fixtures2.filter(**filters):

        # Only account for confirmed scores.
        if not fixture.is_confirmed: continue
        scores = (fixture.score1, fixture.score2)
        row['matches'] += 1

        # Normalize order of scores so that the score of `participant` is first.
        if fixture.player2.id == participant.id:
            scores = scores[::-1]

        # Account points.
        if scores[0] == scores[1]:
            row['draw_count'] += 1
        elif scores[0] > scores[1]:
            row['win_count'] += 1
        elif scores[0] < scores[1]:
            row['loss_count'] += 1

    return row


class Groups(Mode):

    min_group_size = models.PositiveSmallIntegerField()
    max_group_size = models.PositiveSmallIntegerField()
    with_returns   = models.BooleanField(default = False)
    groups_info    = models.JSONField(null = True, blank = True)

    def create_fixtures(self, participants):
        assert len(participants) >= 2

        # Create groups.
        groups = split_into_groups(participants, self.min_group_size, self.max_group_size)
        self.groups_info = [[participant.id for participant in group] for group in groups]
        self.save()

        max_group_size = max((len(group) for group in groups))
        for level, pairings in enumerate(create_division_schedule(np.arange(max_group_size), with_returns = self.with_returns)):

            # Schedule fixtures for each group.
            for group in groups:
                for position, (pidx1, pidx2) in enumerate(pairings):

                    if pidx1 >= len(group) or pidx2 >= len(group): continue
                    Fixture.objects.create(
                        mode     = self,
                        level    = level,
                        position = position,
                        player1  = group[pidx1],
                        player2  = group[pidx2],
                    )

    def get_standings(self, participant):
        row = get_stats(participant, dict(mode = self))
        row['points'] = 3 * row['win_count'] + 1 * row['draw_count']
        return row

    @property
    def standings(self):
        if self.groups_info is None:
            return None
        standings = list()
        for group in self.groups_info:
            group_standings = [self.get_standings(participant) for participant in self.tournament.participants.filter(id__in = group)]
            group_standings.sort(key = lambda row: (row['points'], row['matches'], row['participant'].id), reverse = True)
            standings.append(group_standings)
        return standings

    @property
    def placements(self):
        standings = self.standings
        if standings is None:
            return None
        max_group_size = max((len(group) for group in self.groups_info))
        return [[group[position]['participant'] for group in standings if position < len(group)] for position in range(max_group_size)]


class Knockout(Mode):

    double_elimination = models.BooleanField(default = False)

    def clean(self):
        super(Knockout, self).clean()
        if self.double_elimination:
            raise ValidationError('Double elimination is not implemented yet.')

    @staticmethod
    def reorder_participants(participants, account_for_playoffs):
        """
        Re-order the participants to establish a fair ordering.

        The participants are re-ordered so that the first (highest ranked) are matched against the last (lowest ranked).
        If the number of participants is not a power of 2, playoff matches are required (incomplete levels of the binary tree).
        The order of participants will account for that if `account_for_playoffs` is True, ensuring that the playoffs will be filled up with the very last participants (lowest ranked).
        """
        if len(participants) == 0: return list()

        # Check whether the number of participants is a power of 2.
        power_of_two_floor = 1 << (len(participants).bit_length() - 1)
        power_of_two = (power_of_two_floor == len(participants))

        # Account for playoffs.
        if account_for_playoffs and not power_of_two:

            # Number of participants allocated for the playoffs.
            n = min((2 * (len(participants) - power_of_two_floor), len(participants)))

            # Allocate the participants.
            playoffs_part = Knockout.reorder_participants(participants[-n:], account_for_playoffs = False)
            complete_part = Knockout.reorder_participants(participants[:-n], account_for_playoffs = False)
            return playoffs_part + complete_part

        # Establish the order so that the first are matched against the last.
        result = [None] * len(participants)
        participants = list(participants)
        for pidx in range(len(participants)):
            i = pidx // 2
            j = pidx %  2
            result[pidx] = participants[i if j == 0 else -i - 1]
        return result

    def create_fixtures(self, participants):
        assert len(participants) >= 2
        levels = math.ceil(math.log2(len(participants)))

        # Re-order the participants so that the first (highest ranked) are matched against the last (lowest ranked), also accounting for playoffs.
        participants = Knockout.reorder_participants(participants, account_for_playoffs = True)

        # Identify fixtures by their path (which, in a binary tree, corresponds to the index of the node in binary representation, starting from `1` for the root).
        remaining_participants = list(participants)
        last_fixture_path = len(participants) - 1
        for fixture_path in range(1, last_fixture_path + 1):
            level = levels - int(math.log2(fixture_path)) - 1

            player1 = None if fixture_path * 2 <= last_fixture_path else remaining_participants.pop()
            player2 = None if fixture_path * 2 <  last_fixture_path else remaining_participants.pop()

            Fixture.objects.create(
                mode     = self,
                level    = level,
                position = fixture_path,
                player1  = player1,
                player2  = player2)

        assert len(remaining_participants) == 0, remaining_participants

    def get_parent_fixture(self, fixture):
        if fixture.position == 1: return None
        return self.fixtures.get(position = fixture.position // 2)

    def propagate(self, fixture):
        assert fixture.mode.id == self.id
        assert fixture.winner is not None
        parent_fixture = self.get_parent_fixture(fixture)

        # There is nothing to propagate if `fixture` is the root of the binary tree.
        if parent_fixture is None:
            return False

        # Propagate to either side of the parent fixture.
        if fixture.position % 2 == 0:
            if parent_fixture.player1 is not None:
                return False
            parent_fixture.player1 = fixture.winner
        else:
            if parent_fixture.player2 is not None:
                return False
            parent_fixture.player2 = fixture.winner

        # If anything was propagated, then save.
        parent_fixture.save()
        return True

    def update_fixtures(self):
        updates_performed = False
        for fixture in self.fixtures.all():
            if fixture.is_confirmed:
                if self.propagate(fixture):
                    updates_performed = True
        return updates_performed

    def check_fixture(self, fixture):
        if fixture.score1 is not None and fixture.score2 is not None and fixture.score1 == fixture.score2:
            raise ValidationError('Draws are not allowed in knockout mode.')

    @property
    def placements(self):
        if self.fixtures.count() == 0:
            return None
        final_match = self.fixtures.all()[0]
        return [final_match.winner] + [fixture.loser for fixture in self.fixtures.all()]

    def get_level_name(self, level):
        level = self.levels - level
        assert level >= 1, level
        if level == 1:
            return 'Final'
        if level == 2:
            return 'Semifinals'
        if level == 3:
            return 'Quarter Finals'
        else:
            return f'Last {pow(2, level)}'


class Fixture(models.Model):

    mode     = models.ForeignKey('Mode', on_delete = models.CASCADE, related_name = 'fixtures')
    level    = models.PositiveSmallIntegerField()
    position = models.PositiveSmallIntegerField()
    player1  = models.ForeignKey('auth.User', on_delete = models.PROTECT, related_name = 'fixtures1', null = True)
    player2  = models.ForeignKey('auth.User', on_delete = models.PROTECT, related_name = 'fixtures2', null = True)
    score1   = models.PositiveSmallIntegerField(null = True)
    score2   = models.PositiveSmallIntegerField(null = True)
    confirmations = models.ManyToManyField('auth.User', related_name = 'fixture_confirmations')

    class Meta:
        constraints = [
            CheckConstraint(
                check = (Q(score1__isnull = True) & Q(score2__isnull = True)) | (Q(score1__isnull = False) & Q(score2__isnull = False)),
                name = 'score1 and score2 must be both null or neither')
        ]

    def clean(self):
        super(Fixture, self).clean()
        self.mode.check_fixture(self)

    @property
    def score(self):
        return self.score1, self.score2

    @score.setter
    def score(self, value):
        if isinstance(value, tuple):
            self.score1 = int(value[0])
            self.score2 = int(value[1])
        elif isinstance(value, str):
            value = value.split(':')
            self.score1 = int(value[0])
            self.score2 = int(value[1])
        else:
            raise ValueError(f'unknown value: "{value}"')

    @property
    def players(self):
        return User.objects.filter(Q(fixtures1 = self) | Q(fixtures2 = self))

    @property
    def required_confirmations_count(self):
        return 1 + self.mode.tournament.participations.count() // 2

    @property
    def is_confirmed(self):
        if self.score1 is None or self.score2 is None:
            return False
        return self.confirmations.count() >= self.required_confirmations_count

    @property
    def winner(self):
        if self.score1 is None or self.score2 is None:
            return None
        if self.score1 > self.score2:
            return self.player1
        if self.score1 < self.score2:
            return self.player2
        return None

    @property
    def loser(self):
        if self.score1 is None or self.score2 is None:
            return None
        if self.score1 < self.score2:
            return self.player1
        if self.score1 > self.score2:
            return self.player2
        return None

    def __repr__(self):
        prepr = lambda p: None if p is None else f'{p.username} ({p.id})'
        data = ', '.join([
            f'mode={self.mode}',
            f'level={self.level}',
            f'player1={prepr(self.player1)}',
            f'player2={prepr(self.player2)}',
            f'score1={self.score1}',
            f'score2={self.score2}',
            f'confirmations={self.confirmations.count()} / {self.required_confirmations_count}',
        ])
        return f'<{data}>'
