import math
import random
import re

import numpy as np
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import CheckConstraint, Max, Min, Q, QuerySet
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from polymorphic.models import PolymorphicModel


class Tournament(models.Model):

    name = models.CharField(blank = False, max_length = 100)
    definition = models.TextField(null = True, blank = True)  # noqa: DJ001
    podium_spec = models.JSONField()
    published = models.BooleanField(default = False)
    creator = models.ForeignKey('auth.User', on_delete = models.SET_NULL, related_name = 'tournaments', null = True, blank = True)

    def __str__(self):
        return self.name

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
                Groups.objects.create(**stage)

            elif mode_type == 'knockout':
                Knockout.objects.create(**stage)

            elif mode_type == 'division':
                stage['min_group_size'] = 2
                stage['max_group_size'] = 32767 ## https://docs.djangoproject.com/en/5.0/ref/models/fields/#positivesmallintegerfield
                Groups.objects.create(**stage)

            else:
                raise ValidationError(f'Unknown mode: "{mode_type}".')

        return tournament

    @property
    def participants(self):
        return Participant.objects.filter(participations__tournament = self).order_by('participations__slot_id')

    @property
    def participating_users(self):
        return User.objects.filter(participant__participations__tournament = self).order_by('participant__participations__slot_id')
    
    def get_participant(self, *, user = None, name = None):
        assert (user is None) != (name is None)
        if user is not None:
            return self.participants.get(user = user)
        else:
            return self.participants.get(name = name)

    @property
    def current_stage(self):
        for stage in self.stages.all():
            if not stage.is_finished:
                return stage
        return None ## indicates that the tournament is finished

    @transaction.atomic
    def shuffle_participants(self):
        count = self.participations.count()
        if count == 0:
            return ## early out, so that min/max operations below are well defined
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
                participation = self.participations.get(participant = participant)
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
        return Participant.objects.filter(participations__tournament = self, participations__podium_position__isnull = False).order_by('participations__podium_position')

    def _get_podium(self):
        podium = list()
        for identifier, position in parse_participants_str_list(self.podium_spec):

            try:
                podium_chunk = unwrap_list(self.stages.get(identifier = identifier).placements[position])
            except IndexError as error:
                raise ValueError(f'insufficient participants: {identifier}[{position}] is out of range') from error

            if isinstance(podium_chunk, list):
                podium += podium_chunk
            else:
                podium.append(podium_chunk)
        return podium

    def clean(self):
        super(Tournament, self).clean()
        try:
            for identifier, _ in parse_participants_str_list(self.podium_spec):
                try:
                    self.stages.get(identifier = identifier)
                except Mode.DoesNotExist as error:
                    raise ValueError(f'stage "{identifier}" does not exist') from error
        except Exception as error:
            raise ValidationError(f'Error parsing "podium" definition ({error}).') from error

    @transaction.atomic
    def test(self):
        tournament = Tournament.load(definition = self.definition, name = 'Test')
        for participating_name in (f'--testuser-{pidx}' for pidx in range(len(self.participants))):
            participant = Participant.objects.get_or_create(name = participating_name)[0]
            Participation.objects.create(participant = participant, tournament = tournament, slot_id = Participation.next_slot_id(tournament))

        # Initialize the tournament.
        try:
            tournament.update_state()
        except Exception as error:
            raise ValidationError(f'Error while initializing tournament ({error}).') from error

        # Play through the tournament, always make the participant with the higher ID win.
        while tournament.current_stage is not None:

            assert tournament.current_stage.fixtures.count() > 0
            try:

                # Play the current level, then update the tournament state.
                for fixture in tournament.current_stage.current_fixtures:

                    # If there are only virtual participants...
                    if tournament.participating_users.count() == 0:
                        
                        # ...and the tournament has a creator, then the creator will confirm the fixture.
                        if self.creator is not None:
                            fixture.confirmations.add(self.creator)
                        
                        # ...and the tournament has no creator, then the fixture will be confirmed by an arbitrary user.
                        else:
                            fixture.confirmations.add(User.objects.first())

                    # Otherwise, the participating users will confirm the fixture.
                    else:
                        for user in tournament.participating_users[:fixture.required_confirmations_count]:
                            fixture.confirmations.add(user)

                    fixture.score = (fixture.player1.id, fixture.player2.id)
                    fixture.save()

                tournament.update_state()

            except Exception as error:
                if tournament.current_stage is None:
                    raise ValidationError(f'Error while validating podium ({error}).') from error
                else:
                    raise ValidationError(f'Error while validating "{tournament.current_stage.identifier}" stage ({error}).') from error

        transaction.set_rollback(True)


@receiver(pre_delete, sender=Tournament)
def delete_tournament_stages(sender, instance, **kwargs):
    instance.stages.non_polymorphic().all().delete()


class Participant(models.Model):
    user = models.ForeignKey('auth.User', on_delete = models.SET_NULL, related_name = 'participant', null = True, blank = True)
    name = models.CharField(max_length = 100, unique = True)

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f'<Participant: {self.name} ({self.id})>'

    @staticmethod
    def create_for_user(user):
        return Participant.objects.create(user = user, name = user.username)
    
    @staticmethod
    def get_or_create_for_user(user):
        try:
            return Participant.objects.get(user = user)
        except Participant.DoesNotExist:
            return Participant.create_for_user(user)


class Participation(models.Model):

    participant = models.ForeignKey('Participant', on_delete = models.CASCADE, related_name = 'participations')
    tournament = models.ForeignKey('Tournament', on_delete = models.CASCADE, related_name = 'participations')
    slot_id = models.PositiveIntegerField()
    podium_position = models.PositiveIntegerField(null = True, blank = True)

    class Meta:
        ordering = ('tournament', 'slot_id')
        unique_together = [
            ('tournament', 'slot_id'),
            ('tournament', 'participant'),
            ('tournament', 'podium_position'),
        ]

    def __str__(self):
        return f'{self.participant} in {self.tournament}'

    @staticmethod
    def next_slot_id(tournament):
        return Participation.objects.filter(tournament = tournament).aggregate(Max('slot_id', default = -1))['slot_id__max'] + 1


def parse_participants_str_list(participants_str_list):
    participants = [parse_placements_str(participants_str) for participants_str in participants_str_list]

    # Convert list of (identifier, slice) pairs into list of (identifier, position) pairs.
    references = list()
    for identifier, placements_slice in participants:
        for position in range(placements_slice.stop)[placements_slice]:
            references.append((identifier, position))

    # Verify that the list of participants is disjoint.
    if len(references) > len(frozenset(references)):
        raise ValueError('list of participants is not disjoint')

    return references


def parse_placements_str(placement_str):
    try:
        m = re.match(r'^([a-zA-Z_0-9]+)\.placements\[([-0-9:]+)\]$', placement_str)
        identifier = m.group(1)
        slice_str = m.group(2)
        parts = slice_str.split(':')
        parts = [int(part) if len(part) > 0 else None for part in parts]
        assert 1 <= len(parts) <= 3, slice_str
        if len(parts) == 1:
            parts = parts + [parts[0] + 1]
        placements_slice = slice(*parts)
        return identifier, placements_slice
    except Exception as error:
        raise ValueError(f'cannot parse placement: "{placement_str}"') from error


def unwrap_list(items):
    if isinstance(items, list):
        return unwrap_list(items[0]) if len(items) == 1 else items
    else:
        return items


class Mode(PolymorphicModel):

    identifier = models.SlugField()
    name       = models.CharField(max_length = 100, blank = True)
    tournament = models.ForeignKey('Tournament', on_delete = models.CASCADE, related_name = 'stages')
    played_by  = models.JSONField(default = list, blank = True)

    def clean(self):
        super(Mode, self).clean()
        try:
            for identifier, _ in parse_participants_str_list(self.played_by):
                try:
                    self.tournament.stages.get(identifier = identifier)
                except Mode.DoesNotExist as error:
                    raise ValueError(f'stage "{identifier}" does not exist') from error
        except Exception as error:
            raise ValidationError(f'Error parsing "played_by" definition of "{self.identifier}" stage ({error}).') from error

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
            except IndexError as error:
                raise ValueError(f'insufficient participants: {identifier}[{position}] is out of range') from error

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


def get_stats(participant, filters = None):
    if filters is None:
        filters = dict()

    row = dict(participant = participant, win_count = 0, loss_count = 0, draw_count = 0, matches = 0, balance = 0)
    for fixture in participant.fixtures1.filter(**filters) | participant.fixtures2.filter(**filters):

        # Only account for confirmed scores.
        if not fixture.is_confirmed:
            continue
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

        # Account score balance.
        row['balance'] += scores[0] - scores[1]

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
                for pidx1, pidx2 in pairings:

                    if pidx1 >= len(group) or pidx2 >= len(group): 
                        continue

                    Fixture.objects.create(
                        mode     = self,
                        level    = level,
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
            group_standings.sort(key = lambda row: (row['points'], row['balance'], row['matches'], row['participant'].id), reverse = True)
            standings.append(group_standings)
        return standings

    @property
    def placements(self):
        standings = self.standings
        if standings is None:
            return None
        max_group_size = max((len(group) for group in self.groups_info))
        return [[group[position]['participant'] for group in standings if position < len(group)] for position in range(max_group_size)]


def is_power_of_two(val, ret_floor = False):
    if np.issubdtype(type(val), np.integer):
        val = int(val)
    assert isinstance(val, int), type(val)
    assert val >= 1, val
    power_of_two_floor = 1 << (val.bit_length() - 1)
    power_of_two = power_of_two_floor == val
    if ret_floor:
        return power_of_two, power_of_two_floor
    else:
        return power_of_two


class Knockout(Mode):

    double_elimination = models.BooleanField(default = False)

    @staticmethod
    def reorder_participants(participants, account_for_playoffs):
        """
        Re-order the participants to establish a fair ordering.

        The participants are re-ordered so that the first (highest ranked) are matched against the last (lowest ranked).
        If the number of participants is not a power of 2, playoff matches are required (incomplete levels of the binary tree).
        The order of participants will account for that if `account_for_playoffs` is True, ensuring that the playoffs will be filled up with the very last participants (lowest ranked).
        """
        if len(participants) == 0:
            return list()

        # Check whether the number of participants is a power of 2.
        power_of_two, power_of_two_floor = is_power_of_two(len(participants), ret_floor = True)

        # Account for playoffs.
        if account_for_playoffs and not power_of_two:

            # Number of participants allocated for the playoffs.
            n = min((2 * (len(participants) - power_of_two_floor), len(participants)))

            # Negative indexing is not supported on QuerySet onbjects, thus convert to list.
            if isinstance(participants, QuerySet):
                participants = list(participants)

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

    @staticmethod
    def get_first_complete_level(num_tree1_fixtures):
        """
        Tells the first complete level of the knockout tree.

        This is level 0 if and only if the number of fixtures plus 1 is a power of two (e.g., 3, 7), and level 1 otherwise.
        """
        if is_power_of_two(num_tree1_fixtures + 1):
            return 0
        else:
            return 1

    def create_fixtures(self, participants):
        """
        Creates the fixtures of the knockout tree.

        In single elimination mode, there is only the main tree, which is a binary tree.
        We count the levels of the binary tree from bottom to up (starting with level 0).
        The binary tree is complete, except for layer 0, which may be incomplete.
        An incomplete layer 0 corresponds to playoffs.
        Due to that structure of the main tree, the fixtures of the main tree are fully identified by their *position* within the tree.
        Here, the *position* is the index of the node in binary representation, starting counting from 1 for the root node.

        In double elimination mode, an additional tree is added, which partially overlaps with the main tree and is not binary.
        Also, an additional root node is added, which connects the roots of the two trees (identified by position 0).
        """
        assert len(participants) >= 2
        levels = math.ceil(math.log2(len(participants)))

        # Re-order the participants so that the first (highest ranked) are matched against the last (lowest ranked), also accounting for playoffs.
        participants = Knockout.reorder_participants(participants, account_for_playoffs = True)

        # In double elimination mode, add the additional root node.
        last_fixture_position = len(participants) - 1
        first_complete_level  = Knockout.get_first_complete_level(last_fixture_position)
        if self.double_elimination and len(participants) >= 4:
            double_elimination_root_fixture = Fixture.objects.create(
                mode    = self,
                level   = first_complete_level + 1 + (levels - 1 - first_complete_level) * 2,
                player1 = None,
                player2 = None,
                extras  = dict(position = 0),
            )

        # Build the main tree (embedding the corresponding propagation graph).
        remaining_participants = list(participants)
        tree1_levels, first_tree1_level = list(), -1
        for fixture_position in range(1, last_fixture_position + 1):
            level = levels - int(math.log2(fixture_position)) - 1

            # Create a new list of fixtures for each level.
            if first_tree1_level != level:
                tree1_levels.insert(0, list())
                first_tree1_level = level

            player1 = None if fixture_position * 2 <= last_fixture_position else remaining_participants.pop()
            player2 = None if fixture_position * 2 <  last_fixture_position else remaining_participants.pop()

            extras = dict(tree = 1, position = fixture_position)
            parent_fixture = self.get_main_parent_fixture(fixture_position)
            if parent_fixture is not None:
                extras['propagate'] = dict(
                    winner = dict(
                        fixture_id  = parent_fixture.id,
                        player_slot = 2 if parent_fixture.extras['position'] == 0 else 1 + fixture_position % 2,
                    ),
                )

            fixture = Fixture.objects.create(
                mode    = self,
                level   = level,
                player1 = player1,
                player2 = player2,
                extras  = extras,
            )
            tree1_levels[0].append(fixture)

        # Assert that all participants were distributed.
        assert len(remaining_participants) == 0, remaining_participants

        # In double elimination mode, add the second tree.
        if self.double_elimination and len(participants) >= 4:

            # For each complete level, except the first, add two levels of the second tree.
            complete_tree1_levels = tree1_levels[first_complete_level:]
            previous_tree2_level  = [double_elimination_root_fixture]
            for tree1_level in complete_tree1_levels[1:][::-1]:

                # For each fixture of the main tree, create two fixtures in the second tree.
                tree2_level = list()
                for fidx, tree1_fixture in enumerate(tree1_level):

                    # Create the first fixture (second tree vs. main tree).
                    tree2_fixture1_extras = dict(
                        tree = 2,
                        propagate = dict(
                            winner = dict(
                                fixture_id  = previous_tree2_level[fidx // 2].id,
                                player_slot = 1 + fidx % 2,
                            ),
                        ),
                    )

                    tree2_fixture1 = Fixture.objects.create(
                        mode   = self,
                        level  = first_complete_level + (tree1_fixture.level - first_complete_level) * 2,
                        extras = tree2_fixture1_extras,
                    )

                    # Add propagation from the main to the second tree (and update the level).
                    tree1_fixture.level = first_complete_level - 1 + (tree1_fixture.level - first_complete_level) * 2
                    tree1_fixture.extras['propagate']['loser'] = dict(
                        fixture_id  = tree2_fixture1.id,
                        player_slot = 2,
                    )
                    tree1_fixture.save()

                    # Create the second fixture (second tree vs. second tree, main tree vs. main tree if it is the first level of the second tree).
                    tree2_fixture2_extras = dict(
                        tree = 2,
                        propagate = dict(
                            winner = dict(
                                fixture_id  = tree2_fixture1.id,
                                player_slot = 1,
                            ),
                        ),
                    )

                    tree2_fixture2 = Fixture.objects.create(
                        mode   = self,
                        level  = tree1_fixture.level,
                        extras = tree2_fixture2_extras,
                    )
                    tree2_level.append(tree2_fixture2)

                # Update the reference to the top-most level of the second tree.
                previous_tree2_level = tree2_level

            # Add propagation from the main to the top-most level of the second tree.
            for fidx, tree1_fixture in enumerate(complete_tree1_levels[0]):
                tree1_fixture.extras['propagate']['loser'] = dict(
                    fixture_id  = previous_tree2_level[fidx // 2].id,
                    player_slot = 1 + fidx % 2,
                )
                tree1_fixture.save()

    def get_main_parent_fixture(self, fixture_position):
        """
        Return the parent fixture in the main knockout tree.
        """

        # In double elimination mode, there can be an extra root node.
        if fixture_position == 1:
            try:
                return self.fixtures.get(extras = dict(position = 0))
            except Fixture.DoesNotExist:
                return None

        # Other parent nodes are directly obtained due to the binary tree structure.
        else:
            return self.fixtures.get(extras__tree = 1, extras__position = fixture_position // 2)

    @staticmethod
    def _propagate(src_fixture, src_slot, dst_fixture, dst_player_slot):
        """
        Propagate the value of the `src_slot` attribute of `src_fixture` to the corresponding `player` attribute of `dst_fixture`.

        The corresponding `player` attribute is identified by `dst_play_slot`, which must be 1 or 2.
        """
        player = getattr(src_fixture, src_slot, None)
        assert player is not None
        dst_attr = 'player' + str(dst_player_slot)
        if getattr(dst_fixture, dst_attr) is not None:
            return False
        else:
            setattr(dst_fixture, dst_attr, player)
            dst_fixture.save()
            return True
        

    def propagate(self, fixture):
        assert fixture.mode.id == self.id

        # Keep track of whether anything was propagated.
        propagated = False

        # Propagate along the propagation graph.
        propagate = fixture.extras.get('propagate', dict())
        for slot_name in propagate.keys():
            dst_fixture = self.fixtures.get(id = propagate[slot_name]['fixture_id'])
            _propagated = Knockout._propagate(fixture, slot_name, dst_fixture, propagate[slot_name]['player_slot'])
            propagated  = propagated or _propagated

        # Return whether any updates were performed.
        return propagated

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
        final_match = self.fixtures.get(level = self.levels - 1)
        if not self.double_elimination:
            return [final_match.winner] + [fixture.loser for fixture in self.fixtures.order_by('-level')]
        else:
            chunk1 = [final_match.winner, final_match.loser]
            chunk2 = [fixture.loser for fixture in self.fixtures.filter(extras__tree = 1) if fixture.loser not in chunk1]
            return chunk1 + chunk2

    def get_level_size(self, level):
        """
        Return the maximum possible number of participants in a level of the main tree.

        This is not the actual number of participants, but the maximum number based on the tree structure.
        """
        rlevel = self.levels - level
        assert rlevel >= 1, f'level={level}, self.levels={self.levels}'
        if not self.double_elimination:
            return pow(2, rlevel)
        else:
            return pow(2, rlevel // 2)

    def get_level_name(self, level):
        first_complete_level = Knockout.get_first_complete_level(self.fixtures.filter(extras__tree = 1).count())
        if level < first_complete_level:
            return 'Playoffs'

        level_size = self.get_level_size(level)
        if level_size == 2:
            base_level_name = 'Final'
        elif level_size == 4:
            base_level_name = 'Semifinals'
        elif level_size == 8:
            base_level_name = 'Quarter Finals'
        else:
            base_level_name = f'Last {level_size}'

        if not self.double_elimination:
            return base_level_name

        else:
            if level == first_complete_level:
                return base_level_name
            if level_size <= 2:
                rlevel = self.levels - level
                prefix = {3: '1st', 2: '2nd', 1: '3rd'}[rlevel]
                return f'{prefix} Final Round'
            else:
                prefix = {1: '1st', 0: '2nd'}[(level + first_complete_level) % 2]
                return f'{prefix} {base_level_name}'


class Fixture(models.Model):

    mode    = models.ForeignKey('Mode', on_delete = models.CASCADE, related_name = 'fixtures')
    level   = models.PositiveSmallIntegerField()
    extras  = models.JSONField(default = list, blank = True)
    player1 = models.ForeignKey('Participant', on_delete = models.PROTECT, related_name = 'fixtures1', null = True)
    player2 = models.ForeignKey('Participant', on_delete = models.PROTECT, related_name = 'fixtures2', null = True)
    score1  = models.PositiveSmallIntegerField(null = True)
    score2  = models.PositiveSmallIntegerField(null = True)
    confirmations = models.ManyToManyField('auth.User', related_name = 'fixture_confirmations')

    class Meta:
        constraints = [
            CheckConstraint(
                check = (Q(score1__isnull = True) & Q(score2__isnull = True)) | (Q(score1__isnull = False) & Q(score2__isnull = False)),
                name = 'score1 and score2 must be both null or neither')
        ]

    def __repr__(self):
        data = ', '.join([
            f'mode={self.mode}',
            f'level={self.level}',
            f'player1={repr(self.player1)}',
            f'player2={repr(self.player2)}',
            f'score1={self.score1}',
            f'score2={self.score2}',
            f'confirmations={self.confirmations.count()} / {self.required_confirmations_count}',
        ])
        return f'<{data}>'
    
    def __str__(self):
        return f'{self.player1} vs. {self.player2}'

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
        return 1 + self.mode.tournament.participations.filter(participant__user__isnull = False).count() // 2

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
