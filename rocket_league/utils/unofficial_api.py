from django import template
from django.conf import settings

from ..apps.users.models import LeagueRating

import re
import requests

register = template.Library()

API_BASE = 'https://psyonix-rl.appspot.com'


def api_login():

    HEADERS = {
        'DBVersion': '00.03.0003-00.01.0011',
        'LoginSecretKey': 'dUe3SE4YsR8B0c30E6r7F2KqpZSbGiVx',
        'CallProcKey': 'pX9pn8F4JnBpoO8Aa219QC6N7g18FJ0F',
        'DB': 'BattleCars_Prod',
    }

    login_data = {
        'PlayerName': "RocketLeagueReplays.com",
        'PlayerID': '76561198008869772',
        'Platform': 'Steam',
        'BuildID': 118497356,
    }

    r = requests.post(API_BASE + '/login104/', headers=HEADERS, data=login_data)

    if r.text != '1':
        raise Exception("Unable to login.")

    session_id = re.match(r'SESSIONID=(.*); path=/', r.headers['set-cookie']).group(1)
    HEADERS['Cookie'] = 'SESSIONID=' + session_id

    return HEADERS


def get_leaderboards(headers):

    r = requests.post(API_BASE + '/callproc104/', headers=headers, data={
        'Proc[]': [
            'GetLeaderboard',
        ],
        'P0P[]': [
            'Skill10',
            '1000',  # Get the top 500 for PC and PS4
        ],
    })

    matches = re.findall(r'UserName=(.*)&Value=(\d+)&Platform=(Steam|PSN)(?:&SteamID=(\d+))?', r.text)

    return matches


def get_league_data(user, headers):
    # Does this user have their Steam account connected?
    player_id = user.uid

    r = requests.post(API_BASE + '/callproc104/', headers=headers, data={
        'Proc[]': [
            'GetLeaderboardValueForUserSteam',
            'GetLeaderboardValueForUserSteam',
            'GetLeaderboardValueForUserSteam',
        ],
        'P0P[]': [
            player_id,
            'Skill{}'.format(settings.PLAYLISTS['RankedDuels']),
        ],
        'P1P[]': [
            player_id,
            'Skill{}'.format(settings.PLAYLISTS['RankedDoubles']),
        ],
        'P2P[]': [
            player_id,
            'Skill{}'.format(settings.PLAYLISTS['RankedStandard']),
        ]
    })

    matches = re.findall(r'LeaderboardID=Skill(\d+)&Value=(\d+)', r.text)

    if not matches:
        return 'no matches'

    matches = dict(matches)

    # Store this, cache it, do something with it.
    LeagueRating.objects.create(
        user_id=user.user_id,
        duels=matches[str(settings.PLAYLISTS['RankedDuels'])],
        doubles=matches[str(settings.PLAYLISTS['RankedDoubles'])],
        standard=matches[str(settings.PLAYLISTS['RankedStandard'])],
    )

    return matches
