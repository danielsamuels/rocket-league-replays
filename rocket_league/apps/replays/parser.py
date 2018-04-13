import json
import math
import os
import pdb
import subprocess
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from pprint import pprint
from sys import platform

import pytz
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from pyrope import Replay as Pyrope


def distance(pos1, pos2):
    xd = pos2[0] - pos1[0]
    yd = pos2[1] - pos1[1]
    zd = pos2[2] - pos1[2]

    return math.sqrt(xd * xd + yd * yd + zd * zd)


# Convert the Pyrope data structure to the rattletrap structure.
def _pyrope_to_rattletrap(replay):
    from .models import PLATFORMS_MAPPINGS

    data = {}

    simple_keys = [
        'MaxChannels', 'Team0Score', 'Team1Score', 'PlayerName', 'KeyframeDelay',
        'MaxReplaySizeMB', 'NumFrames', 'MatchType', 'MapName', 'ReplayName',
        'PrimaryPlayerTeam', 'Id', 'TeamSize', 'RecordFPS', 'Date'
    ]

    for key in simple_keys:
        data[key] = {
            'kind': 'default',
            'value': replay.header.get(key, ''),
        }

    integers = ['Team0Score', 'Team1Score', 'NumFrames', 'PrimaryPlayerTeam']

    for key in integers:
        if data[key]['value'] == '':
            data[key]['value'] = 0

    if 'PlayerStats' in replay.header:
        data['PlayerStats'] = {
            'kind': 'ArrayProperty',
            'value': {
                'array_property': []
            },
        }

        for player in replay.header['PlayerStats']:
            player_data = {}
            simple_keys = [
                'Goals', 'Saves', 'Shots', 'Score', 'Team', 'bBot', 'Assists', 'Name', 'OnlineID',
            ]

            for key in simple_keys:
                player_data[key] = {
                    'kind': 'default',
                    'value': player[key],
                }

            player_data['Platform'] = {
                'kind': 'default',
                'value': PLATFORMS_MAPPINGS[player['Platform']['OnlinePlatform']],
            }

            data['PlayerStats']['value']['array_property'].append({'value': player_data})

    if 'Goals' in replay.header:
        data['Goals'] = {
            'kind': 'default',
            'value': []
        }

        for goal in replay.header['Goals']:
            goal_data = {}
            keys = ['frame', 'PlayerName', 'PlayerTeam']

            for key in keys:
                goal_data[key] = {
                    'kind': 'default',
                    'value': goal[key],
                }

            data['Goals']['value'].append(goal_data)

    return {
        'header': {
            'properties': {
                'value': data,
            }
        }
    }


def get_value(data, key, default=None):
    key_data = data.get(key, {
        'kind': 'default',
        'value': default,
    })

    if key_data['kind'] == 'default':
        return key_data['value']
    if key_data['kind'] == 'IntProperty':
        return key_data['value']['int_property']
    elif key_data['kind'] == 'StrProperty':
        return key_data['value']['str_property']
    elif key_data['kind'] == 'NameProperty':
        return key_data['value']['name_property']
    elif key_data['kind'] == 'FloatProperty':
        return key_data['value']['float_property']
    elif key_data['kind'] == 'ArrayProperty':
        return [
            item['value']
            for item in key_data['value']['array_property']
        ]
    else:
        raise Exception('get_value: {} not handled'.format(key_data['kind']))


def get_replication_value(value):
    key = list(value.keys())[0]
    value = value[key]

    if isinstance(value, dict):
        if key == 'flagged_int_attribute_value':
            return value['int']

        elif key == 'unique_id_attribute_value':
            if value['system_id'] == 1:
                return {
                    'local_id': value['local_id'],
                    'remote_id': value['remote_id']['steam_id'],
                    'system_id': value['system_id'],
                }
            elif value['system_id'] == 2:
                return {
                    'local_id': value['local_id'],
                    'remote_id': value['remote_id']['play_station_id'][0],
                    'system_id': value['system_id'],
                }
            elif value['system_id'] == 4:
                return {
                    'local_id': value['local_id'],
                    'remote_id': value['remote_id']['xbox_id'],
                    'system_id': value['system_id'],
                }
            else:
                return {
                    'local_id': value.get('local_id', 0),
                    'remote_id': 0,
                    'system_id': value['system_id'],
                }

        elif key == 'party_leader_attribute_value':
            if value['system_id'] == 1:
                return value['id'][0]['steam_id']
            elif value['system_id'] == 2:
                return value['id'][0]['play_station_id'][0]
            elif value['system_id'] == 4:
                return value['id'][0]['xbox_id']
            else:
                return 0
        elif key in [
            # Data we don't need.
            'reservation_attribute_value',
            'team_paint_attribute_value',
            'explosion_attribute_value',
            'extended_explosion_attribute_value',
            'music_stinger_attribute_value',
            'demolish_attribute_value',
        ]:
            return []

        elif key in [
            # Not sure about
            'loadouts_online_attribute_value',
            'loadouts_attribute_value',

            # Definitely need
            'rigid_body_state_attribute_value',
            'cam_settings_attribute_value',
            'loadout_attribute_value',
            'pickup_attribute_value',
            'location_attribute_value',
        ]:
            # print(key, value)
            return value
        else:
            # print('before raise', value)
            # print('get_replication_value: {} not handled'.format(key))
            return []
    else:
        return value


def flatten_value(value):
    if isinstance(value, dict):
        return value

    return {
        item['name']: {
            'id': item['id']['value'],
            'value': get_replication_value(item['value']),
        }
        for item in value
    }


def _parse_header(replay_obj, replay):
    from .models import BoostData, Goal, Map, Player, Season

    Goal.objects.filter(replay=replay_obj).delete()
    Player.objects.filter(replay=replay_obj).delete()
    BoostData.objects.filter(replay=replay_obj).delete()

    assert Goal.objects.filter(replay=replay_obj).count() == 0
    assert Player.objects.filter(replay=replay_obj).count() == 0
    assert BoostData.objects.filter(replay=replay_obj).count() == 0

    # Assign the metadata to the replay object.
    header = replay['header']['properties']['value']

    replay_obj.replay_id = get_value(header, 'Id')

    if 'TeamSize' in header:
        replay_obj.team_sizes = get_value(header, 'TeamSize')
    elif 'PlayerStats' in header:
        replay_obj.team_sizes = math.ceil(len(get_value(header, 'PlayerStats')) / 2.0)

    replay_obj.team_0_score = get_value(header, 'Team0Score', 0)
    replay_obj.team_1_score = get_value(header, 'Team1Score', 0)
    replay_obj.player_name = get_value(header, 'PlayerName')
    replay_obj.player_team = get_value(header, 'PrimaryPlayerTeam', 0)
    replay_obj.match_type = get_value(header, 'MatchType')
    replay_obj.keyframe_delay = get_value(header, 'KeyframeDelay')
    replay_obj.max_channels = get_value(header, 'MaxChannels')
    replay_obj.max_replay_size_mb = get_value(header, 'MaxReplaySizeMB')
    replay_obj.num_frames = get_value(header, 'NumFrames')
    replay_obj.record_fps = get_value(header, 'RecordFPS')

    if get_value(header, 'MapName', False):
        map_obj, _ = Map.objects.get_or_create(
            slug=get_value(header, 'MapName').lower(),
        )
    else:
        map_obj = None

    replay_obj.map = map_obj

    try:
        replay_obj.timestamp = timezone.make_aware(
            datetime.fromtimestamp(
                time.mktime(
                    time.strptime(
                        get_value(header, 'Date'),
                        '%Y-%m-%d:%H-%M',
                    )
                )
            ),
            timezone.get_current_timezone()
        )
    except pytz.exceptions.AmbiguousTimeError:
        replay_obj.timestamp = timezone.make_aware(
            datetime.fromtimestamp(
                time.mktime(
                    time.strptime(
                        get_value(header, 'Date'),
                        '%Y-%m-%d:%H-%M',
                    )
                )
            ) + timedelta(hours=1),
            timezone.get_current_timezone()
        )
    except ValueError:
        try:
            replay_obj.timestamp = timezone.make_aware(
                datetime.fromtimestamp(
                    time.mktime(
                        time.strptime(
                            get_value(header, 'Date'),
                            '%Y-%m-%d %H-%M-%S',
                        )
                    )
                ),
                timezone.get_current_timezone()
            )
        except pytz.exceptions.AmbiguousTimeError:
            replay_obj.timestamp = timezone.make_aware(
                datetime.fromtimestamp(
                    time.mktime(
                        time.strptime(
                            get_value(header, 'Date'),
                            '%Y-%m-%d %H-%M-%S',
                        )
                    )
                ) + timedelta(hours=1),
                timezone.get_current_timezone()
            )

    replay_obj.season = Season.objects.filter(
        start_date__lte=replay_obj.timestamp,
    ).first()

    replay_obj.title = get_value(header, 'ReplayName', None)

    return replay_obj, replay, header


def parse_replay_header(replay_id):
    from .models import Replay, Player, Goal

    replay_obj = Replay.objects.get(pk=replay_id)

    replay = Pyrope(replay_obj.file.read())

    replay = _pyrope_to_rattletrap(replay)
    replay_obj, replay, header = _parse_header(replay_obj, replay)

    # Create the player objects.
    if 'PlayerStats' in header:
        for player in get_value(header, 'PlayerStats', []):
            Player.objects.get_or_create(
                replay=replay_obj,
                player_name=get_value(player, 'Name'),
                platform=get_value(player, 'Platform'),
                saves=get_value(player, 'Saves'),
                score=get_value(player, 'Score'),
                goals=get_value(player, 'Goals'),
                shots=get_value(player, 'Shots'),
                team=get_value(player, 'Team'),
                assists=get_value(player, 'Assists'),
                bot=get_value(player, 'bBot'),
                online_id=get_value(player, 'OnlineID'),
            )
    else:
        # The best we can do is to get the goal scorers and the player.
        for goal in get_value(header, 'Goals', []):
            Player.objects.get_or_create(
                replay=replay_obj,
                player_name=get_value(goal, 'PlayerName'),
                team=get_value(goal, 'PlayerTeam'),
            )

        if 'PlayerName' in header:
            team = 0

            if 'PrimaryPlayerTeam' in header:
                team = get_value(header, 'PrimaryPlayerTeam')

            Player.objects.get_or_create(
                replay=replay_obj,
                player_name=get_value(header, 'PlayerName'),
                team=team,
            )

    # Create the goal objects.
    if 'Goals' in header:
        for index, goal in enumerate(get_value(header, 'Goals', [])):
            player = None

            players = Player.objects.filter(
                replay=replay_obj,
                player_name=get_value(goal, 'PlayerName'),
                team=get_value(goal, 'PlayerTeam'),
            )

            if players.count() > 0:
                player = players[0]
            else:
                player = Player.objects.create(
                    replay=replay_obj,
                    player_name=get_value(goal, 'PlayerName'),
                    team=get_value(goal, 'PlayerTeam'),
                )

            try:
                goal_obj = Goal.objects.get(
                    replay=replay_obj,
                    frame=get_value(goal, 'frame'),
                    number=index + 1,
                    player=player,
                )

                goal_obj.delete()
            except Goal.DoesNotExist:
                pass

            Goal.objects.create(
                replay=replay_obj,
                frame=get_value(goal, 'frame'),
                number=index + 1,
                player=player,
            )

    replay_obj.processed = True
    replay_obj.crashed_heatmap_parser = False
    replay_obj.save()


def parse_replay_netstream(replay_id):
    from .models import PLATFORMS, BoostData, Goal, Player, Replay

    replay_obj = Replay.objects.get(pk=replay_id)

    try:
        if settings.DEBUG or platform == 'darwin':
            if not os.path.isfile(replay_obj.file.path):
                # Download the file.
                command = 'wget https://media.rocketleaguereplays.com/{} -qO {}'.format(
                    replay_obj.file.name,
                    replay_obj.file.path,
                )

                os.system(command)

            replay = json.loads(subprocess.check_output('rattletrap-binaries/rattletrap-*-osx -i {}'.format(
                replay_obj.file.path
            ), shell=True).decode('utf-8'))
        else:
            replay_name = replay_obj.file.name.split('/')[-1]

            command = 'wget {} -qO /tmp/{}'.format(
                replay_obj.file.url,
                replay_name,
            )

            os.system(command)

            replay = json.loads(subprocess.check_output('rattletrap-binaries/rattletrap-*-linux -i /tmp/{}'.format(
                replay_name,
            ), shell=True).decode('utf-8'))

            command = 'rm /tmp/{}'.format(
                replay_name,
            )

            os.system(command)

    except subprocess.CalledProcessError:
        # Parsing the file failed.
        replay_obj.processed = False
        replay_obj.save()
        return

    replay_obj, replay, header = _parse_header(replay_obj, replay)

    goals = {
        get_value(goal, 'frame'): {
            'PlayerName': get_value(goal, 'PlayerName'),
            'PlayerTeam': get_value(goal, 'PlayerTeam')
        }
        for goal in get_value(header, 'Goals', [])
    }

    last_hits = {
        0: None,
        1: None
    }

    actors = {}  # All actors
    player_actors = {}  # XXX: This will be used to make the replay.save() easier.
    match_goals = {}
    teaminfo_score = {}
    goal_actors = {}
    team_data = {}
    actor_positions = {}  # The current position data for all actors. Do we need this?
    player_cars = {}  # Car -> Player actor ID mappings.
    boost_components = {}  # Archetypes.CarComponents.CarComponent_Boost objects
    ball_angular_velocity = None  # The current angular velocity of the ball.
    ball_possession = None  # The team currently in possession of the ball.
    cars_frozen = False  # Whether the cars are frozen in place (3.. 2.. 1..)
    shot_data = []  # The locations of the player and the ball when goals were scored.
    unknown_boost_data = {}  # Holding dict for boosts without player data.
    ball_actor_id = None

    location_data = []  # Used for the location JSON.
    boost_data = {}  # Used for the boost stats.
    boost_objects = []
    heatmap_data = {}
    seconds_mapping = {}  # Frame -> seconds remaining mapping.

    heatmap_json_filename = 'uploads/replay_json_files/{}.json'.format(replay_obj.replay_id)
    location_json_filename = 'uploads/replay_location_json_files/{}.json'.format(replay_obj.replay_id)

    for index, frame in enumerate(replay['content']['frames']):
        # Add an empty location list for this frame.
        location_data.append([])

        ball_hit = False
        confirmed_ball_hit = False
        ball_spawned = False

        if index in goals:
            # Get the ball position.
            ball_actor_id = list(filter(lambda x: actors[x]['class_name'] in ['TAGame.Ball_TA', 'TAGame.Ball_Breakout_TA'], actors))[0]
            ball_position = actor_positions[ball_actor_id]

            # XXX: Update this to also register the hitter?
            hit_position = last_hits[goals[index]['PlayerTeam']]

            shot_data.append({
                'player': hit_position,
                'ball': ball_position,
                'frame': index
            })

            # Reset the last hits.
            last_hits = {
                0: None,
                1: None
            }

        # Handle any new actors.
        for replication in frame['replications']:
            actor_id = int(replication['actor_id']['value'])
            replication_type = list(replication['value'].keys())[0]
            value = replication['value'][replication_type]
            flattened_value = flatten_value(value)

            if replication_type == 'spawned_replication_value':
                if actor_id not in actors:
                    actors[actor_id] = value

                if 'Engine.Pawn:PlayerReplicationInfo' in flattened_value:
                    player_actor_id = value['Engine.Pawn:PlayerReplicationInfo']['value']
                    player_cars[player_actor_id] = actor_id

                if value['class_name'] == 'TAGame.Ball_TA':
                    ball_spawned = True
                elif value['class_name'] == 'TAGame.PRI_TA':
                    player_actors[actor_id] = value
                    player_actors[actor_id]['joined'] = index
                elif value['class_name'] == 'TAGame.Team_Soccar_TA':
                    team_data[actor_id] = value['object_name'].replace('Archetypes.Teams.Team', '')

            # Handle any updates to existing actors.
            elif replication_type == 'updated_replication_value':
                if (
                    'Engine.PlayerReplicationInfo:Team' in flattened_value and
                    not flattened_value['Engine.PlayerReplicationInfo:Team']['value']
                ):
                    del flattened_value['Engine.PlayerReplicationInfo:Team']

                # If an actor is getting their team value nuked, store what it was
                # so we can use it later on.
                if (
                    'Engine.PlayerReplicationInfo:Team' in flattened_value and
                    flattened_value['Engine.PlayerReplicationInfo:Team']['value'] == -1 and
                    actors[actor_id]['Engine.PlayerReplicationInfo:Team']['value'] != -1
                ):
                    actors[actor_id]['Engine.PlayerReplicationInfo:CachedTeam'] = actors[actor_id]['Engine.PlayerReplicationInfo:Team']

                # Merge the new properties with the existing.
                if actors[actor_id] != value:
                    actors[actor_id] = {**actors[actor_id], **flattened_value}

                    if actor_id in player_actors:
                        player_actors[actor_id] = actors[actor_id]

                if 'Engine.Pawn:PlayerReplicationInfo' in flattened_value:
                    player_actor_id = flattened_value['Engine.Pawn:PlayerReplicationInfo']['value']
                    player_cars[player_actor_id] = actor_id

            # Handle removing any destroyed actors.
            elif replication_type == 'destroyed_replication_value':
                del actors[actor_id]

                if actor_id in player_actors:
                    player_actors[actor_id]['left'] = index
            else:
                raise Exception('Unhandled replication_type: {}'.format(replication_type))

        # Loop over actors which have changed in this frame.
        for replication in frame['replications']:
            actor_id = int(replication['actor_id']['value'])
            replication_type = list(replication['value'].keys())[0]
            value = replication['value'][replication_type]
            flattened_value = flatten_value(value)

            if replication_type not in ['spawned_replication_value', 'updated_replication_value']:
                continue

            # Look for any position data.
            if 'TAGame.RBActor_TA:ReplicatedRBState' in flattened_value:
                location = flattened_value['TAGame.RBActor_TA:ReplicatedRBState']['value']['location']
                rotation = flattened_value['TAGame.RBActor_TA:ReplicatedRBState']['value']['rotation']

                actor_positions[actor_id] = [location['x'], location['y'], location['z']]

                # Get the player actor id.
                real_actor_id = actor_id

                for player_actor_id, car_actor_id in player_cars.items():
                    if actor_id == car_actor_id:
                        real_actor_id = player_actor_id
                        break

                if real_actor_id == actor_id:
                    real_actor_id = 'ball'

                data_dict = {'id': real_actor_id}
                data_dict['x'] = location['x']
                data_dict['y'] = location['y']
                data_dict['z'] = location['z']

                # print(rotation)
                data_dict['roll'] = rotation['x']['value']
                data_dict['pitch'] = rotation['y']['value']
                data_dict['yaw'] = rotation['z']['value']

                location_data[index].append(data_dict)

            # If this property exists, the ball has changed possession.
            if 'TAGame.Ball_TA:HitTeamNum' in flattened_value:
                ball_hit = confirmed_ball_hit = True
                hit_team_num = flattened_value['TAGame.Ball_TA:HitTeamNum']['value']
                ball_possession = hit_team_num

                # Clean up the actor positions.
                actor_positions_copy = actor_positions.copy()
                for actor_position in actor_positions_copy:
                    found = False

                    for car in player_cars:
                        if actor_position == player_cars[car]:
                            found = True

                    if not found and actor_position != ball_actor_id:
                        del actor_positions[actor_position]

            # Store the boost data for each actor at each frame where it changes.
            if 'TAGame.CarComponent_Boost_TA:ReplicatedBoostAmount' in flattened_value:
                boost_value = flattened_value['TAGame.CarComponent_Boost_TA:ReplicatedBoostAmount']['value']
                assert 0 <= boost_value <= 255, 'Boost value {} is not in range 0-255.'.format(boost_value)

                if actor_id not in boost_data:
                    boost_data[actor_id] = {}

                # Sometimes we have a boost component without a reference to
                # a car. We don't want to lose that data, so stick it into a
                # holding dictionary until we can figure out who it belongs to.

                if 'TAGame.CarComponent_TA:Vehicle' not in actors[actor_id]:
                    if actor_id not in unknown_boost_data:
                        unknown_boost_data[actor_id] = {}

                    unknown_boost_data[actor_id][index] = boost_value
                else:
                    car_id = actors[actor_id]['TAGame.CarComponent_TA:Vehicle']['value']

                    # Find out which player this car belongs to.
                    try:
                        player_actor_id = [
                            player_actor_id
                            for player_actor_id, car_actor_id in player_cars.items()
                            if car_actor_id == car_id
                        ][0]

                        if player_actor_id not in boost_data:
                            boost_data[player_actor_id] = {}

                        boost_data[player_actor_id][index] = boost_value

                        # Attach any floating data (if we can).
                        if actor_id in unknown_boost_data:
                            for frame_index, boost_value in unknown_boost_data[actor_id].items():
                                boost_data[player_actor_id][frame_index] = boost_value

                            del unknown_boost_data[actor_id]

                    except IndexError:
                        pass

            # Store the mapping of frame -> clock time.
            if 'TAGame.GameEvent_Soccar_TA:SecondsRemaining' in flattened_value:
                seconds_mapping[index] = flattened_value['TAGame.GameEvent_Soccar_TA:SecondsRemaining']['value']

            # See if the cars are frozen in place.
            if 'TAGame.GameEvent_TA:ReplicatedGameStateTimeRemaining' in flattened_value:
                if flattened_value['TAGame.GameEvent_TA:ReplicatedGameStateTimeRemaining']['value'] == 3:
                    cars_frozen = True
                elif flattened_value['TAGame.GameEvent_TA:ReplicatedGameStateTimeRemaining']['value'] == 0:
                    cars_frozen = False

            # Get the camera details.
            if 'TAGame.CameraSettingsActor_TA:ProfileSettings' in flattened_value:
                if actors[actor_id]['class_name'] == 'TAGame.CameraSettingsActor_TA':
                    # Define some short variable names to stop the next line
                    # being over 200 characters long.  This block of code
                    # makes new replays have a camera structure which is
                    # similar to that of the old replays - where the camera
                    # settings are directly attached to the player rather
                    # than a CameraActor (which is what the actor in this
                    # current loop is).

                    csa = 'TAGame.CameraSettingsActor_TA:PRI'
                    ps = 'TAGame.CameraSettingsActor_TA:ProfileSettings'
                    cs = 'TAGame.PRI_TA:CameraSettings'

                    if csa in flattened_value:
                        player_actor_id = flattened_value[csa]['value']
                        actors[player_actor_id][cs] = flattened_value[ps]['value']

            if 'Engine.GameReplicationInfo:ServerName' in flattened_value:
                replay_obj.server_name = flattened_value['Engine.GameReplicationInfo:ServerName']['value']

            if 'ProjectX.GRI_X:ReplicatedGamePlaylist' in flattened_value:
                replay_obj.playlist = flattened_value['ProjectX.GRI_X:ReplicatedGamePlaylist']['value']

            if 'TAGame.GameEvent_Team_TA:MaxTeamSize' in flattened_value:
                replay_obj.team_sizes = flattened_value['TAGame.GameEvent_Team_TA:MaxTeamSize']['value']

            if 'TAGame.PRI_TA:MatchGoals' in flattened_value:
                # Get the closest goal to this frame.
                mg = flattened_value['TAGame.PRI_TA:MatchGoals']
                mg_increased = False

                if mg['value'] > match_goals.get(actor_id, 0):
                    match_goals[actor_id] = mg['value']
                    mg_increased = True

                if index not in match_goals and mg_increased:
                    goal_actors[index] = actor_id
                    match_goals[actor_id] = mg['value']

            if 'Engine.TeamInfo:Score' in flattened_value:
                tis = flattened_value['Engine.TeamInfo:Score']
                tis_increased = False

                if tis['value'] > teaminfo_score.get(actor_id, 0):
                    teaminfo_score[actor_id] = tis['value']
                    tis_increased = True

                if index not in goal_actors and tis_increased:
                    goal_actors[index] = actor_id

        # Work out which direction the ball is travelling and if it has
        # changed direction or speed.
        ball = None
        ball_actor_id = None
        for actor_id, value in actors.items():
            if value['class_name'] == 'TAGame.Ball_TA':
                ball_actor_id = actor_id
                ball = value
                break

        ball_hit = False

        # Take a look at the ball this frame, has anything changed?
        if (
            ball and
            'TAGame.RBActor_TA:ReplicatedRBState' in ball and
            'angular_velocity' in ball['TAGame.RBActor_TA:ReplicatedRBState']['value']
        ):
            new_ball_angular_velocity = ball['TAGame.RBActor_TA:ReplicatedRBState']['value']['angular_velocity']

            # The ball has *changed direction*, but not necessarily been hit (it
            # may have bounced).

            if ball_angular_velocity != new_ball_angular_velocity:
                ball_hit = True

            ball_angular_velocity = new_ball_angular_velocity

            # Calculate the current distances between cars and the ball.
            # Do we have position data for the ball?
            if ball_hit and not ball_spawned and ball_actor_id in actor_positions:

                # Iterate over the cars to get the players.
                lowest_distance = None
                lowest_distance_car_actor = None

                for player_id, car_actor_id in player_cars.items():
                    # Get the team.
                    if (
                        player_id in actors and
                        'Engine.PlayerReplicationInfo:Team' in actors[player_id] and
                        actors[player_id]['Engine.PlayerReplicationInfo:Team']['value']
                    ):
                        team_id = actors[player_id]['Engine.PlayerReplicationInfo:Team']['value']

                        try:
                            team_actor = actors[team_id]
                            team = int(team_actor['object_name'].replace('Archetypes.Teams.Team', '').replace('GameEvent_Soccar_TA_', ''))
                        except KeyError:
                            team = -1
                    else:
                        team = -1

                    # Make sure this actor is in on the team which is currently
                    # in possession.

                    if team != ball_possession:
                        continue

                    if car_actor_id in actor_positions:
                        actor_distance = distance(actor_positions[car_actor_id], actor_positions[ball_actor_id])

                        if not confirmed_ball_hit:
                            if actor_distance > 350:  # Value taken from the max confirmed distance.
                                continue

                        # Get the player on this team with the lowest distance.
                        if lowest_distance is None or actor_distance < lowest_distance:
                            lowest_distance = actor_distance
                            lowest_distance_car_actor = car_actor_id

                if lowest_distance_car_actor:
                    last_hits[ball_possession] = actor_positions[lowest_distance_car_actor]

        # Generate the heatmap data for this frame.  Get all of the players
        # and the ball.
        if not cars_frozen:
            moveable_actors = [
                (actor_id, value)
                for actor_id, value in actors.items()
                if value['class_name'] in ['TAGame.Ball_TA', 'TAGame.PRI_TA', 'TAGame.Car_TA'] and
                (
                    'TAGame.RBActor_TA:ReplicatedRBState' in value or
                    'location' in value
                )
            ]

            for actor_id, value in moveable_actors:
                if value['class_name'] == 'TAGame.Ball_TA':
                    actor_id = 'ball'
                elif value['class_name'] == 'TAGame.Car_TA':
                    if 'Engine.Pawn:PlayerReplicationInfo' not in value:
                        continue

                    actor_id = value['Engine.Pawn:PlayerReplicationInfo']['value']

                if 'TAGame.RBActor_TA:ReplicatedRBState' in value:
                    key = '{},{}'.format(
                        value['TAGame.RBActor_TA:ReplicatedRBState']['value']['location']['x'],
                        value['TAGame.RBActor_TA:ReplicatedRBState']['value']['location']['y'],
                    )
                elif 'location' in value:
                    key = '{},{}'.format(
                        value['location']['x'],
                        value['location']['y'],
                    )

                if actor_id not in heatmap_data:
                    heatmap_data[actor_id] = {}

                if key in heatmap_data[actor_id]:
                    heatmap_data[actor_id][key] += 1
                else:
                    heatmap_data[actor_id][key] = 1

    def get_team(actor_id):
        if actor_id == -1:
            return -1

        return int(actors[actor_id]['object_name'].replace('Archetypes.Teams.Team', ''))

    player_objects = {}

    # Make a dict of all the player actors and then do a bulk_create?
    for actor_id, value in player_actors.items():
        if 'Engine.PlayerReplicationInfo:UniqueId' in value:
            system = value['Engine.PlayerReplicationInfo:UniqueId']['value']['system_id']
            local_id = value['Engine.PlayerReplicationInfo:UniqueId']['value']['local_id']
            online_id = value['Engine.PlayerReplicationInfo:UniqueId']['value']['remote_id']

            unique_id = '{system}-{remote}-{local}'.format(
                system=system,
                remote=online_id,
                local=local_id,
            )
        else:
            system = 'Unknown'
            unique_id = ''
            online_id = ''

        team = -1

        if 'Engine.PlayerReplicationInfo:Team' in value and value['Engine.PlayerReplicationInfo:Team']['value']:
            team = get_team(value['Engine.PlayerReplicationInfo:Team']['value'])

        # Attempt to get the team ID from our cache.
        if team == -1 and 'Engine.PlayerReplicationInfo:CachedTeam' in value:
            team = get_team(value['Engine.PlayerReplicationInfo:CachedTeam']['value'])

        if team == -1:
            # If this is a 1v1 and the other player has a team, then put this
            # player on the opposite team.
            if len(player_actors) == 2:
                pak = list(player_actors.keys())
                other_player = player_actors[pak[(pak.index(actor_id) - 1) * -1]]

                other_team = -1

                if 'Engine.PlayerReplicationInfo:Team' in other_player and other_player['Engine.PlayerReplicationInfo:Team']['value']:
                    other_team = other_player['Engine.PlayerReplicationInfo:Team']['value']

                # Attempt to get the team ID from our cache.
                if other_team == -1 and 'Engine.PlayerReplicationInfo:CachedTeam' in other_player:
                    other_team = other_player['Engine.PlayerReplicationInfo:CachedTeam']['value']

                if other_team != -1:
                    # There's nothing more we can do.
                    tdk = list(team_data.keys())
                    team_id = tdk[(tdk.index(other_team) - 1) * 1]
                    team = get_team(team_id)

                    player_actors[actor_id]['Engine.PlayerReplicationInfo:Team'] = {
                        'Type': 'FlaggedInt',
                        'Value': {
                            'Flag': True,
                            'Int': team_id,
                        }
                    }

        player_objects[actor_id] = Player.objects.create(
            replay=replay_obj,
            player_name=value['Engine.PlayerReplicationInfo:PlayerName']['value'],
            team=team,
            score=value.get('TAGame.PRI_TA:MatchScore', {'value': 0})['value'],
            goals=value.get('TAGame.PRI_TA:MatchGoals', {'value': 0})['value'],
            shots=value.get('TAGame.PRI_TA:MatchShots', {'value': 0})['value'],
            assists=value.get('TAGame.PRI_TA:MatchAssists', {'value': 0})['value'],
            saves=value.get('TAGame.PRI_TA:MatchSaves', {'value': 0})['value'],
            platform=PLATFORMS.get(system, system),
            online_id=online_id,
            bot=value.get('Engine.PlayerReplicationInfo:bBot', {'value': False})['value'],
            spectator='Engine.PlayerReplicationInfo:Team' not in value,
            actor_id=actor_id,
            unique_id=unique_id,
            camera_settings=value.get('TAGame.PRI_TA:CameraSettings', None),
            vehicle_loadout=value.get('TAGame.PRI_TA:ClientLoadout', {'value': {}})['value'],
            total_xp=value.get('TAGame.PRI_TA:TotalXP', {'value': 0})['value'],
        )

        # Store the boost data for this player.
        for boost_frame, boost_value in boost_data.get(actor_id, {}).items():
            boost_objects.append(BoostData(
                replay=replay_obj,
                player=player_objects[actor_id],
                frame=boost_frame,
                value=boost_value,
            ))

    BoostData.objects.bulk_create(boost_objects)

    # Create the goals.
    goal_objects = []
    goal_actors = OrderedDict(sorted(goal_actors.items()))

    for index, actor_id in goal_actors.items():
        # Use the player_objects dict rather than the full actors dict as
        # players who leave the game get removed from the latter.

        if actor_id in player_actors:
            goal_objects.append(Goal(
                replay=replay_obj,
                number=len(goal_objects) + 1,
                player=player_objects[actor_id],
                frame=index,
            ))

        # This actor is most likely the team object, meaning the goal was an
        # own goal scored without any of the players on the benefiting team
        # hitting the ball.

        elif actor_id in actors:
            if actors[actor_id]['class_name'] == 'TAGame.Team_Soccar_TA':
                own_goal_player, _ = Player.objects.get_or_create(
                    replay=replay_obj,
                    player_name='Unknown player (own goal?)',
                    team=get_team(actor_id),
                )

                goal_objects.append(Goal(
                    replay=replay_obj,
                    number=len(goal_objects) + 1,
                    player=own_goal_player,
                    frame=index,
                ))

    Goal.objects.bulk_create(goal_objects)

    # Generate heatmap and location JSON files.

    # Put together the heatmap file.
    replay_obj.heatmap_json_file = default_storage.save(
        heatmap_json_filename,
        ContentFile(json.dumps(heatmap_data, separators=(',', ':')))
    )

    # Put together the location JSON file.

    # Get rid of any boost data keys which have an empty value.
    for actor_id, data in boost_data.copy().items():
        if not data:
            del boost_data[actor_id]

    goal_data = [
        {
            'PlayerName': get_value(goal, 'PlayerName'),
            'PlayerTeam': get_value(goal, 'PlayerTeam'),
            'frame': get_value(goal, 'frame'),
        }
        for goal in get_value(header, 'Goals', [])
    ]

    # Trim down the actors to just the information we care about.
    player_data = {
        actor_id: {
            'type': 'player',
            'join': data['joined'],
            'left': data.get('left', get_value(header, 'NumFrames')),
            'team': data['Engine.PlayerReplicationInfo:Team']['value'],
            'name': data['Engine.PlayerReplicationInfo:PlayerName']['value']
        }
        for actor_id, data in player_actors.items()
        if 'Engine.PlayerReplicationInfo:Team' in data
    }

    final_data = {
        'frame_data': location_data,
        'goals': goal_data,
        'boost': boost_data,
        'seconds_mapping': seconds_mapping,
        'actors': player_data,
        'teams': team_data,
    }

    replay_obj.location_json_file = default_storage.save(
        location_json_filename,
        ContentFile(json.dumps(final_data, separators=(',', ':')))
    )

    replay_obj.shot_data = shot_data
    replay_obj.processed = True
    replay_obj.show_leaderboard = True
    replay_obj.crashed_heatmap_parser = False

    replay_obj.excitement_factor = replay_obj.calculate_excitement_factor()
    replay_obj.average_rating = replay_obj.calculate_average_rating()

    replay_obj.save()
