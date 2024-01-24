from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

import numpy as np

from tournaments.models import (
    split_into_groups,
    create_division_schedule,
    parse_played_by,
    Tournament,
    Participation,
    Mode,
    Groups,
    Knockout,
    Fixture,
)


test_tournament1_yml = \
    """
    stages:
    - 
      id: preliminaries
      name: Group ${ group_letter }
      mode: groups
      min-group-size: 3
      max-group-size: 4
    -
      id: main_round
      name: Main Round
      mode: knockout
      played-by:
      - groups.placements[0]
      - groups.placements[1]
    -
      id: playoffs
      name: Playoffs
      mode: division
      played-by:
      - main_round.placements[2]
      - main_round.placements[3]

    podium:
    - main_round.placements[0]
    - main_round.placements[1]
    - playoffs.placements[0]
    """

test_tournament2_yml = \
    """
    stages:
    -
      id: main_round
      mode: knockout
      double-elimination: true
    -
      id: playoffs
      name: Playoffs
      mode: division
      played-by:
      - main_round.placements[2]
      - main_round.placements[3]

    podium:
    - main_round.placements[0]
    - main_round.placements[1]
    - playoffs.placements[0]
    """


class split_into_groups_Test(TestCase):

    def test_even(self):
        actual = split_into_groups([1, 2, 3, 4], min_group_size=1, max_group_size=1)
        expected = [
            [1],
            [2],
            [3],
            [4],
        ]
        self.assertEqual(actual, expected)

        actual = split_into_groups([1, 2, 3, 4], min_group_size=2, max_group_size=2)
        expected = [
            [1, 3],
            [2, 4],
        ]
        self.assertEqual(actual, expected)

    def test_uneven(self):
        actual = split_into_groups([1, 2, 3, 4, 5], min_group_size=1, max_group_size=2)
        expected = [
            [1, 4],
            [2, 5],
            [3],
        ]
        self.assertEqual(actual, expected)


class create_division_schedule_Test(TestCase):

    def test_even_with_returns(self):
        actual = create_division_schedule([1, 2, 3, 4], with_returns = True)
        assert_division_schedule_validity(self, actual, with_returns = True)

    def test_even_without_returns(self):
        actual = create_division_schedule([1, 2, 3, 4], with_returns = False)
        assert_division_schedule_validity(self, actual, with_returns = False)

    def test_uneven_with_returns(self):
        actual = create_division_schedule([1, 2, 3], with_returns = True)
        assert_division_schedule_validity(self, actual, with_returns = True)

        actual = create_division_schedule([1, 2, 3, 4, 5], with_returns = True)
        assert_division_schedule_validity(self, actual, with_returns = True)

    def test_uneven_without_returns(self):
        actual = create_division_schedule([1, 2, 3], with_returns = False)
        assert_division_schedule_validity(self, actual, with_returns = False)

        actual = create_division_schedule([1, 2, 3, 4, 5], with_returns = False)
        assert_division_schedule_validity(self, actual, with_returns = False)


class parse_played_by_Test(TestCase):

    def setUp(self):
        self.placements = list(np.arange(10))

    def test_literal(self):
        actual = parse_played_by('stage.placements[0]')
        self.assertEqual(actual[0], 'stage')
        self.assertEqual(self.placements[actual[1]], [0])

    def test_sequence(self):
        actual = parse_played_by('stage.placements[:2]')
        self.assertEqual(actual[0], 'stage')
        self.assertEqual(self.placements[actual[1]], [0, 1])

    def test_sequence_with_offset(self):
        actual = parse_played_by('stage.placements[1:3]')
        self.assertEqual(actual[0], 'stage')
        self.assertEqual(self.placements[actual[1]], [1, 2])

    def test_sequence_reverse(self):
        actual = parse_played_by('stage.placements[1::-1]')
        self.assertEqual(actual[0], 'stage')
        self.assertEqual(self.placements[actual[1]], [1, 0])


def assert_division_schedule_validity(test, schedule, with_returns):
    try:
        participants = list(np.unique(sum(schedule, list())))
        n = len(participants)
        A = np.zeros((n, n))
        I = lambda p: participants.index(p)
        for pairings in schedule:
            matchday_participants = set()
            for p1, p2 in pairings:

                test.assertFalse(p1 in matchday_participants, f'{p1} included multiple times in matchday {pairings}')
                test.assertFalse(p2 in matchday_participants, f'{p2} included multiple times in matchday {pairings}')

                A[I(p1), I(p2)] += 1

                matchday_participants.add(p1)
                matchday_participants.add(p2)

        if with_returns:
            A += np.eye(n)
            test.assertTrue((A == 1).all(), f'pairings missing or duplicate:\n{A}')

        else:
            A += A.T
            A += np.eye(n)
            test.assertTrue((A[np.tril_indices(n)] == 1).all(), f'pairings missing or duplicate:\n{A}')

    except:
        print(f'*** Schedule: {schedule}')
        raise


def _add_participants(participants_pool, tournament):
    for participant in participants_pool:
        Participation.objects.create(
            user = participant,
            tournament = tournament,
            slot_id = Participation.next_slot_id(tournament))


def _clear_participants(tournament):
    Participation.objects.filter(tournament = tournament).delete()


def _confirm_fixture(participants, fixture, score1 = 0, score2 = 0):
    n = fixture.required_confirmations_count
    for participant in participants[:n]:
        fixture.confirmations.add(participant)

    fixture.score = (score1, score2)
    fixture.save()


class ModeTestBase:

    def setUp(self):
        self.tournament = Tournament.objects.create(name = 'Test', podium = list())
        self.participants = list()
        for user_idx in range(10):
            user = User.objects.create_user(
                id = user_idx + 1,
                username = f'user-{user_idx + 1}',
                password =  'password')
            self.participants.append(user)

    def add_participants(self, tournament, number):
        _add_participants(self.participants[:number], tournament)

    def clear_participants(self, tournament):
        _clear_participants(tournament)

    def confirm_fixture(self, *args, **kwargs):
        _confirm_fixture(self.participants, *args, **kwargs)

    def group_fixtures_by_level(self, mode):
        actual_fixtures = dict()
        pid = lambda p: None if p is None else p.id
        for fixture in mode.fixtures.all():
            actual_fixtures.setdefault(fixture.level, list())
            actual_fixtures[fixture.level].append((pid(fixture.player1), pid(fixture.player2)))
        return actual_fixtures


class ModeTest(ModeTestBase, TestCase):

    def test_participants_default(self):
        self.add_participants(self.tournament, 8)
        mode = Mode.objects.create(tournament = self.tournament)
        actual_participants = [p.id for p in mode.participants]
        expected_participants = [p.id for p in self.participants[:8]]
        self.assertEqual(actual_participants, expected_participants)
        return mode

    def test_participants_from_groups(self):
        self.add_participants(self.tournament, 8)
        mode1 = Groups.objects.create(tournament = self.tournament, min_group_size = 3, max_group_size = 4, slug = 'groups')
        mode1.create_fixtures(mode1.participants)
        mode2 = Mode.objects.create(
            tournament = self.tournament,
            played_by = [
                'groups.placements[0]',
                'groups.placements[1]',
            ]
        )
        p11, p12 = mode1.groups_info[0][:2 ]
        p21, p22 = mode1.groups_info[1][-2:]

        # Score most points to p11 and p21, and second-most to p12 and p22.
        for fixture in mode1.fixtures.all():
            if fixture.player1.id in (p11, p21):
                self.confirm_fixture(fixture, 1, 0)
            elif fixture.player2.id in (p11, p21):
                self.confirm_fixture(fixture, 0, 1)
            elif fixture.player1.id in (p12, p22):
                self.confirm_fixture(fixture, 1, 0)
            elif fixture.player2.id in (p12, p22):
                self.confirm_fixture(fixture, 0, 1)
            else:
                self.confirm_fixture(fixture, 0, 0)

        # Verify participants of the next stage.
        actual_participants = [p.id for p in mode2.participants]
        expected_participants = [p11, p21, p12, p22]
        self.assertEqual(actual_participants, expected_participants)

    def test_participants_from_knockout(self):
        self.add_participants(self.tournament, 8)
        mode1 = Knockout.objects.create(tournament = self.tournament, slug = 'knockout')
        mode1.create_fixtures(mode1.participants)
        mode2 = Mode.objects.create(
            tournament = self.tournament,
            played_by = [
                'knockout.placements[0]',
                'knockout.placements[1]',
            ]
        )
        p1, p2 = mode1.participants[:2]

        # Set p1 and p2 for the finals and let p1 win.
        final = mode1.fixtures.all()[0]
        final.player1 = User.objects.get(id = p1.id)
        final.player2 = User.objects.get(id = p2.id)
        self.confirm_fixture(final, 1, 0)

        # Verify participants of the next stage.
        actual_participants = [p.id for p in mode2.participants]
        expected_participants = [p1.id, p2.id]
        self.assertEqual(actual_participants, expected_participants)


class GroupsTest(ModeTestBase, TestCase):

    def test_create_fixtures_minimal(self):
        mode = Groups.objects.create(tournament = self.tournament, min_group_size = 2, max_group_size = 2)
        mode.create_fixtures(self.participants[:2])

        # Verify groups.
        actual_groups_info = mode.groups_info
        expected_groups_info = [
            [1, 2],
        ]
        self.assertEqual(actual_groups_info, expected_groups_info)

        # Verify fixtures.
        actual_fixtures = self.group_fixtures_by_level(mode)
        expected_fixtures = {
            0: [(1, 2)],
        }
        self.assertEqual(actual_fixtures, expected_fixtures)

    def test_create_fixtures_extended(self):
        mode = Groups.objects.create(tournament = self.tournament, min_group_size = 2, max_group_size = 3)
        mode.create_fixtures(self.participants[:5])

        # Verify groups.
        actual_groups_info = mode.groups_info
        expected_groups_info = [
            [1, 3, 5],
            [2, 4],
        ]
        self.assertEqual(actual_groups_info, expected_groups_info)

        # Verify fixtures.
        actual_fixtures = self.group_fixtures_by_level(mode)
        expected_fixtures = {
            0: [(5, 3)],
            1: [(1, 5)],
            2: [(3, 1), (4, 2)]
        }
        self.assertEqual(actual_fixtures, expected_fixtures)

        return mode

    def test_levels(self):
        mode = self.test_create_fixtures_extended()
        self.assertEqual(mode.levels, 3)

    def test_current_fixtures(self):
        mode = self.test_create_fixtures_extended()

        # Test on level 0.
        self.assertEqual(mode.current_level, 0)
        self.assertEqual(mode.current_fixtures.count(), 1)

        fixture = mode.current_fixtures.get()
        self.assertEqual(fixture.player1.id, 5)
        self.assertEqual(fixture.player2.id, 3)

        self.confirm_fixture(fixture)

        # Test on level 1.
        self.assertEqual(mode.current_level, 1)
        self.assertEqual(mode.current_fixtures.count(), 1)

        fixture = mode.current_fixtures.get()
        self.assertEqual(fixture.player1.id, 1)
        self.assertEqual(fixture.player2.id, 5)

        self.confirm_fixture(fixture)

        # Test on level 2.
        self.assertEqual(mode.current_level, 2)
        self.assertEqual(mode.current_fixtures.count(), 2)

        fixtures = mode.current_fixtures.all()
        self.assertEqual(fixtures[0].player1.id, 3)
        self.assertEqual(fixtures[0].player2.id, 1)
        self.assertEqual(fixtures[1].player1.id, 4)
        self.assertEqual(fixtures[1].player2.id, 2)

        self.confirm_fixture(fixtures[0])
        self.assertEqual(mode.current_level, 2)
        self.confirm_fixture(fixtures[1])

        # Test on level 3.
        self.assertEqual(mode.current_level, 3)
        self.assertIsNone(mode.current_fixtures)

    def test_standings(self):
        mode = self.test_create_fixtures_extended()
        self.add_participants(self.tournament, 5)

        # Test on level 0 (no scores yet).
        expected_standings = [
            [
                {
                    'participant': User.objects.get(id = 5),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
                {
                    'participant': User.objects.get(id = 3),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
                {
                    'participant': User.objects.get(id = 1),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
            ],
            [
                {
                    'participant': User.objects.get(id = 4),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
                {
                    'participant': User.objects.get(id = 2),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
            ],
        ]
        self.assertEqual(mode.standings, expected_standings)

        # Test on level 1 (user-5 vs. user-3).
        fixture = mode.current_fixtures.get()
        self.confirm_fixture(fixture, score1 = 8, score2 = 7)
        expected_standings = [
            [
                {
                    'participant': User.objects.get(id = 5),
                    'win_count': 1,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 3,
                    'matches': 1,
                },
                {
                    'participant': User.objects.get(id = 3),
                    'win_count': 0,
                    'loss_count': 1,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 1,
                },
                {
                    'participant': User.objects.get(id = 1),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
            ],
            [
                {
                    'participant': User.objects.get(id = 4),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
                {
                    'participant': User.objects.get(id = 2),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
            ],
        ]
        self.assertEqual(mode.standings, expected_standings)

        # Test on level 2 (user-1 vs. user-5).
        fixture = mode.current_fixtures.get()
        self.confirm_fixture(fixture, score1 = 5, score2 = 5)
        expected_standings = [
            [
                {
                    'participant': User.objects.get(id = 5),
                    'win_count': 1,
                    'loss_count': 0,
                    'draw_count': 1,
                    'points': 4,
                    'matches': 2,
                },
                {
                    'participant': User.objects.get(id = 1),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 1,
                    'points': 1,
                    'matches': 1,
                },
                {
                    'participant': User.objects.get(id = 3),
                    'win_count': 0,
                    'loss_count': 1,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 1,
                },
            ],
            [
                {
                    'participant': User.objects.get(id = 4),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
                {
                    'participant': User.objects.get(id = 2),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
            ],
        ]
        self.assertEqual(mode.standings, expected_standings)

        # Test on level 3 (user-3 vs. user-1).
        fixture1, fixture2 = mode.current_fixtures.all()
        self.confirm_fixture(fixture1, score1 = 6, score2 = 9)
        expected_standings = [
            [
                {
                    'participant': User.objects.get(id = 5),
                    'win_count': 1,
                    'loss_count': 0,
                    'draw_count': 1,
                    'points': 4,
                    'matches': 2,
                },
                {
                    'participant': User.objects.get(id = 1),
                    'win_count': 1,
                    'loss_count': 0,
                    'draw_count': 1,
                    'points': 4,
                    'matches': 2,
                },
                {
                    'participant': User.objects.get(id = 3),
                    'win_count': 0,
                    'loss_count': 2,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 2,
                },
            ],
            [
                {
                    'participant': User.objects.get(id = 4),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
                {
                    'participant': User.objects.get(id = 2),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 0,
                },
            ],
        ]
        self.assertEqual(mode.standings, expected_standings)

        # Test on level 3 (user-4 vs. user-2).
        self.confirm_fixture(fixture2, score1 = 5, score2 = 5)
        expected_standings = [
            [
                {
                    'participant': User.objects.get(id = 5),
                    'win_count': 1,
                    'loss_count': 0,
                    'draw_count': 1,
                    'points': 4,
                    'matches': 2,
                },
                {
                    'participant': User.objects.get(id = 1),
                    'win_count': 1,
                    'loss_count': 0,
                    'draw_count': 1,
                    'points': 4,
                    'matches': 2,
                },
                {
                    'participant': User.objects.get(id = 3),
                    'win_count': 0,
                    'loss_count': 2,
                    'draw_count': 0,
                    'points': 0,
                    'matches': 2,
                },
            ],
            [
                {
                    'participant': User.objects.get(id = 4),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 1,
                    'points': 1,
                    'matches': 1,
                },
                {
                    'participant': User.objects.get(id = 2),
                    'win_count': 0,
                    'loss_count': 0,
                    'draw_count': 1,
                    'points': 1,
                    'matches': 1,
                },
            ],
        ]
        self.assertEqual(mode.standings, expected_standings)

        return mode

    def test_placements(self):
        mode = self.test_standings()
        expected_placements = [
            [
                User.objects.get(id = 5),
                User.objects.get(id = 4),
            ],
            [
                User.objects.get(id = 1),
                User.objects.get(id = 2),
            ],
            [
                User.objects.get(id = 3),
            ],
        ]
        self.assertEqual(mode.placements, expected_placements)

    def test_placements_none(self):
        mode = Groups.objects.create(tournament = self.tournament, min_group_size = 2, max_group_size = 2)
        self.assertIsNone(mode.placements)

    def test_required_confirmations_count(self):
        expected_counts = {
            2: 2,
            3: 2,
            4: 3,
            5: 3,
            6: 4,
            7: 4,
            8: 5,
        }
        for n in range(2, 9):
            with self.subTest(n = n):
                mode = Groups.objects.create(tournament = self.tournament, min_group_size = 2, max_group_size = 2)
                self.clear_participants(self.tournament)
                self.add_participants(self.tournament, n)
                mode.create_fixtures(self.participants[:n])
                for fixture in mode.fixtures.all():
                    self.assertEqual(fixture.required_confirmations_count, expected_counts[n])

class KnockoutTest(ModeTestBase, TestCase):

    def test_create_fixtures_2participants(self):
        mode = Knockout.objects.create(tournament = self.tournament)
        mode.create_fixtures(self.participants[:2])

        # Verify fixtures.
        actual_fixtures = self.group_fixtures_by_level(mode)
        expected_fixtures = {
            0: [(2, 1)],
        }
        self.assertEqual(actual_fixtures, expected_fixtures)

        return mode

    def test_create_fixtures_4participants(self):
        mode = Knockout.objects.create(tournament = self.tournament)
        mode.create_fixtures(self.participants[:4])

        # Verify fixtures.
        actual_fixtures = self.group_fixtures_by_level(mode)
        expected_fixtures = {
            0: [(4, 3), (2, 1)],
            1: [(None, None)]
        }
        self.assertEqual(actual_fixtures, expected_fixtures)

    def test_create_fixtures_5participants(self):
        mode = Knockout.objects.create(tournament = self.tournament)
        mode.create_fixtures(self.participants[:5])

        # Verify fixtures.
        actual_fixtures = self.group_fixtures_by_level(mode)
        expected_fixtures = {
            0: [(2, 1)],
            1: [(None, 5), (4, 3)],
            2: [(None, None)]
        }
        self.assertEqual(actual_fixtures, expected_fixtures)

        return mode

    def test_create_fixtures_6participants(self):
        mode = Knockout.objects.create(tournament = self.tournament)
        mode.create_fixtures(self.participants[:6])

        # Verify fixtures.
        actual_fixtures = self.group_fixtures_by_level(mode)
        expected_fixtures = {
            0: [(4, 3), (2, 1)],
            1: [(None, None), (6, 5)],
            2: [(None, None)]
        }
        self.assertEqual(actual_fixtures, expected_fixtures)

    def test_check_fixture(self):
        mode = self.test_create_fixtures_2participants()
        fixture = mode.fixtures.get()

        # Verify that draws are forbidden.
        fixture.score = (10, 10)
        self.assertRaises(ValidationError, fixture.clean)

        # Verify that other results are allowed.
        fixture.score = (10, 12)
        fixture.clean()
        fixture.save()
        fixture.refresh_from_db()
        self.assertEqual(fixture.score1, 10)
        self.assertEqual(fixture.score2, 12)

    def test_propagate(self):
        mode = self.test_create_fixtures_5participants()
        playoff = mode.current_fixtures.get()

        # Propagate play-off (user-2 vs. user-1).
        playoff.score = (10, 12)
        playoff.save()
        propagate_ret = mode.propagate(playoff)
        self.assertTrue(propagate_ret)

        # Verify fixtures after play-off.
        actual_fixtures = self.group_fixtures_by_level(mode)
        expected_fixtures = {
            0: [(2, 1)],
            1: [(1, 5), (4, 3)],
            2: [(None, None)]
        }
        self.assertEqual(actual_fixtures, expected_fixtures)

        # Propagate 1st seminfal (user-1 vs. user-5).
        semifinal1 = mode.fixtures.get(player1 = User.objects.get(id = 1), player2 = User.objects.get(id = 5))
        semifinal1.score = (12, 10)
        semifinal1.save()
        propagate_ret = mode.propagate(semifinal1)
        self.assertTrue(propagate_ret)

        # Verify fixtures after 1st semifinal.
        actual_fixtures = self.group_fixtures_by_level(mode)
        expected_fixtures = {
            0: [(2, 1)],
            1: [(1, 5), (4, 3)],
            2: [(1, None)]
        }
        self.assertEqual(actual_fixtures, expected_fixtures)

        # Propagate 2nd seminfal (user-4 vs. user-3).
        semifinal2 = mode.fixtures.get(player1 = User.objects.get(id = 4), player2 = User.objects.get(id = 3))
        semifinal2.score = (12, 10)
        semifinal2.save()
        propagate_ret = mode.propagate(semifinal2)
        self.assertTrue(propagate_ret)

        # Test redundant propgatation.
        propagate_ret = mode.propagate(semifinal2)
        self.assertFalse(propagate_ret)

        # Verify fixtures after 2nd semifinal.
        actual_fixtures = self.group_fixtures_by_level(mode)
        expected_fixtures = {
            0: [(2, 1)],
            1: [(1, 5), (4, 3)],
            2: [(1, 4)]
        }
        self.assertEqual(actual_fixtures, expected_fixtures)

        # Propagate final (user-1 vs. user-4).
        final = mode.fixtures.get(player1 = User.objects.get(id = 1), player2 = User.objects.get(id = 4))
        final.score = (12, 10)
        final.save()
        propagate_ret = mode.propagate(final)
        self.assertFalse(propagate_ret)

        return mode

    def test_levels(self):
        mode = self.test_create_fixtures_5participants()
        self.assertEqual(mode.levels, 3)

    def test_current_fixtures(self):
        mode = self.test_propagate()

        # Test on level 0.
        self.assertEqual(mode.current_level, 0)
        self.assertEqual(mode.current_fixtures.count(), 1)

        fixture = mode.current_fixtures.get()
        self.assertEqual(fixture.player1.id, 2)
        self.assertEqual(fixture.player2.id, 1)

        self.confirm_fixture(fixture)

        # Test on level 1.
        self.assertEqual(mode.current_level, 1)
        self.assertEqual(mode.current_fixtures.count(), 2)

        fixtures = mode.current_fixtures.all()
        self.assertEqual(fixtures[0].player1.id, 1)
        self.assertEqual(fixtures[0].player2.id, 5)
        self.assertEqual(fixtures[1].player1.id, 4)
        self.assertEqual(fixtures[1].player2.id, 3)

        self.confirm_fixture(fixtures[0])
        self.assertEqual(mode.current_level, 1)
        self.confirm_fixture(fixtures[1])

        # Test on level 2.
        self.assertEqual(mode.current_level, 2)
        self.assertEqual(mode.current_fixtures.count(), 1)

        fixture = mode.current_fixtures.get()
        self.assertEqual(fixture.player1.id, 1)
        self.assertEqual(fixture.player2.id, 4)

        self.confirm_fixture(fixture)

        # Test on level 3.
        self.assertEqual(mode.current_level, 3)
        self.assertIsNone(mode.current_fixtures)

    def test_placements(self):
        mode = self.test_propagate()
        actual_placements = [user.id for user in mode.placements]
        expected_placements = [1, 4, 5, 3, 2]
        self.assertEqual(actual_placements, expected_placements)

    def test_placements_empty(self):
        mode = self.test_create_fixtures_5participants()
        expected_placements = [None, None, None, None, None]
        self.assertEqual(mode.placements, expected_placements)

    def test_placements_none(self):
        mode = Knockout.objects.create(tournament = self.tournament)
        self.assertIsNone(mode.placements)


class FixtureTest(TestCase):

    def setUp(self):
        self.tournament = Tournament.objects.create(name = 'Test', podium = list())
        self.knockout   = Knockout.objects.create(tournament = self.tournament)
        self.players    = [
            User.objects.create(
                id = user_idx + 1,
                username = f'user-{user_idx + 1}',
                password =  'password')
            for user_idx in range(2)
        ]
        self.fixture = Fixture.objects.create(mode = self.knockout, level = 0, position = 0, player1 = self.players[0], player2 = self.players[1])

    def test_score(self):
        self.assertEqual(self.fixture.score, (None, None))
        self.fixture.score = (10, 12)
        self.assertEqual(self.fixture.score, (10, 12))
        self.fixture.score = '12:10'
        self.assertEqual(self.fixture.score, (12, 10))

    def test_winner(self):
        self.assertIsNone(self.fixture.winner)
        self.fixture.score = (10, 12)
        self.assertEqual(self.fixture.winner.id, self.players[1].id)
        self.fixture.score = (12, 10)
        self.assertEqual(self.fixture.winner.id, self.players[0].id)
        self.fixture.score = (10, 10)
        self.assertIsNone(self.fixture.winner)

    def test_loser(self):
        self.assertIsNone(self.fixture.loser)
        self.fixture.score = (10, 12)
        self.assertEqual(self.fixture.loser.id, self.players[0].id)
        self.fixture.score = (12, 10)
        self.assertEqual(self.fixture.loser.id, self.players[1].id)
        self.fixture.score = (10, 10)
        self.assertIsNone(self.fixture.loser)


class TournamentTest(TestCase):

    def setUp(self):
        self.participants = [
            User.objects.create(
                id = user_idx + 1,
                username = f'user-{user_idx + 1}',
                password =  'password')
            for user_idx in range(8)
        ]

    def test_load_tournament1(self):
        tournament = Tournament.load(test_tournament1_yml, 'Test Cup')
        actual_stages = [type(stage) for stage in tournament.stages.all()]
        expected_stages = [
            Groups,
            Knockout,
            Groups,
        ]
        self.assertEqual(actual_stages, expected_stages)
        return tournament

    def test_load_tournament2(self):
        tournament = Tournament.load(test_tournament2_yml, 'Test Cup')
        actual_stages = [type(stage) for stage in tournament.stages.all()]
        expected_stages = [
            Knockout,
            Groups,
        ]
        self.assertEqual(actual_stages, expected_stages)
        return tournament

    def test_current_stage(self):
        tournament = self.test_load_tournament1()
        self.assertEqual(tournament.current_stage.id, tournament.stages.all()[0].id)

        _add_participants(self.participants, tournament)

        tournament.current_stage.create_fixtures(self.participants)
        self.assertEqual(tournament.current_stage.id, tournament.stages.all()[0].id)

        for fixture in tournament.current_stage.fixtures.all():
            _confirm_fixture(self.participants, fixture)
        self.assertEqual(tournament.current_stage.id, tournament.stages.all()[1].id)

        tournament.current_stage.create_fixtures(self.participants)
        self.assertEqual(tournament.current_stage.id, tournament.stages.all()[1].id)

        for fixture in tournament.current_stage.fixtures.all():
            _confirm_fixture(self.participants, fixture)
        self.assertEqual(tournament.current_stage.id, tournament.stages.all()[2].id)

        tournament.current_stage.create_fixtures(self.participants)
        self.assertEqual(tournament.current_stage.id, tournament.stages.all()[2].id)

        for fixture in tournament.current_stage.fixtures.all():
            _confirm_fixture(self.participants, fixture)
        self.assertIsNone(tournament.current_stage)
