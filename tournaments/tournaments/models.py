import math
import re

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CheckConstraint, Q, Max

from polymorphic.models import PolymorphicModel

import numpy as np


class Tournament(models.Model):

    name = models.CharField(blank = False, max_length = 100)
    podium_spec = models.JSONField()

    @staticmethod
    def load(definition, name):
        if isinstance(definition, str):
            import yaml
            definition = yaml.safe_load(definition)

        assert isinstance(definition, dict), repr(definition)
        tournament = Tournament.objects.create(name = name, podium_spec = definition['podium'])

        for stage in definition['stages']:
            stage = {key.replace('-', '_'): value for key, value in stage.items()}
            stage['tournament'] = tournament

            if 'id' in stage.keys( ):
                stage['identifier'] = stage.pop('id')

            mode_type = stage.pop('mode')

            if mode_type == 'groups':
                mode = Groups.objects.create(**stage)

            if mode_type == 'knockout':
                mode = Knockout.objects.create(**stage)

            if mode_type == 'division':
                stage['min_group_size'] = 2
                stage['max_group_size'] = 32767 ## https://docs.djangoproject.com/en/5.0/ref/models/fields/#positivesmallintegerfield
                mode = Groups.objects.create(**stage)

        return tournament

    @property
    def participants(self):
        return User.objects.filter(participations__tournament = self)

    @property
    def current_stage(self):
        for stage in self.stages.all():
            if not stage.is_finished:
                return stage
        return None ## indicates that the tournament is finished

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
    def podium(self):
        return User.objects.filter(participations__tournament = self, participations__podium_position__isnull = False).order_by('participations__podium_position')

    def _get_podium(self):
        podium = list()
        for podium_entry in self.podium_spec:
            identifier, placements_slice = parse_placements_str(podium_entry)
            podium_chunk = unwrap_list(self.stages.get(identifier = identifier).placements[placements_slice])
            if isinstance(podium_chunk, list):
                podium += podium_chunk
            else:
                podium.append(podium_chunk)
        return podium


class Participation(models.Model):

    user = models.ForeignKey('auth.User', on_delete = models.PROTECT, related_name = 'participations')
    tournament = models.ForeignKey('Tournament', on_delete = models.CASCADE, related_name = 'participations')
    slot_id = models.PositiveIntegerField()
    podium_position = models.PositiveIntegerField(null = True)

    @staticmethod
    def next_slot_id(tournament):
        return Participation.objects.filter(tournament = tournament).count() + 1

    class Meta:
        ordering = ('tournament', 'slot_id')
        unique_together = [
            ('tournament', 'slot_id'),
            ('tournament', 'user'),
            ('tournament', 'podium_position'),
        ]


def parse_placements_str(played_by):
    m = re.match(r'^([a-zA-Z_0-9]+)\.placements\[([-0-9:]+)\]$', played_by)
    identifier = m.group(1)
    slice_str = m.group(2)
    parts = slice_str.split(':')
    parts = [int(part) if len(part) > 0 else None for part in parts]
    assert 1 <= len(parts) <= 3, slice_str
    if len(parts) == 1: parts = parts + [parts[0] + 1]
    placements_slice = slice(*parts)
    return identifier, placements_slice


def unwrap_list(items):
    if isinstance(items, list):
        return unwrap_list(items[0]) if len(items) == 1 else items
    else:
        return items


class Mode(PolymorphicModel):

    identifier = models.SlugField()
    name = models.CharField(max_length = 100)
    tournament = models.ForeignKey('Tournament', on_delete = models.CASCADE, related_name = 'stages')
    played_by  = models.JSONField(default = list)

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
        for played_by in self.played_by:
            identifier, placements_slice = parse_placements_str(played_by)
            participants_chunk = unwrap_list(self.tournament.stages.get(identifier = identifier).placements[placements_slice])
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

    # Return all non-empty groups.
    return [group for group in groups if len(group) > 0]


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
    groups_info    = models.JSONField(null = True)

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

    def create_fixtures(self, participants):
        assert len(participants) >= 2
        levels = math.ceil(math.log2(len(participants)))

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
            raise ValidationError('draws are not allowed in knockout mode')

    @property
    def placements(self):
        if self.fixtures.count() == 0:
            return None
        final, semifinal1, semifinal2 = self.fixtures.all()[:3]
        return [final.winner] + [fixture.loser for fixture in self.fixtures.all()]


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
