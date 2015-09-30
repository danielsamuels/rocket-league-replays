from __future__ import absolute_import

from rocket_league.apps.users.models import SteamUser

from celery import shared_task
import requests


@shared_task
def get_username(steam, users):
    if not isinstance(users, SteamUser):
        # Get this user's display name and update the record.
        info = steam.ISteamUser.GetPlayerSummaries(
            steamids=[user.steam_id for user in users],
        )

        data = info['response']['players']

        for player in data:
            for user in users:
                if user.steam_id == player['steamid']:
                    user.username = player['personaname']
                    user.save()
    else:
        # Get this user's display name and update the record.
        info = steam.ISteamUser.GetPlayerSummaries(
            steamids=[users.steam_id],
        )

        user.username = info['response']['players'][0]['personaname']
        user.save()


@shared_task
def get_friends(steam, steam_id):
    friends = steam.ISteamUser.GetFriendList(
        steamid=steam_id,
    )

    process_friends.delay(steam, friends)


@shared_task
def process_friends(steam, friends):
    try:
        for friend in friends['friendslist']['friends']:
            # If we already have this user in the database, don't make an
            # (expensive) call to the Steam API.

            try:
                SteamUser.objects.get(
                    steam_id=friend['steamid']
                )
            except SteamUser.DoesNotExist:
                games = steam.IPlayerService.GetOwnedGames(
                    steamid=friend['steamid'],
                    include_played_free_games=False,
                    include_appinfo=False,
                    appids_filter=['252950']
                )

                # The user owns Rocket League.
                if games['response']:
                    user, created = SteamUser.objects.get_or_create(
                        steam_id=friend['steamid'],
                    )
    except requests.exceptions.HTTPError:
        pass
