from django.core.management.base import BaseCommand
from django.conf import settings

from ...models import SteamUser

from rocket_league.apps.users.tasks import get_friends, get_username
from .....utils.unofficial_api import api_login, get_leaderboards

from steam import WebAPI


class Command(BaseCommand):
    help = "Get data from as many people on Steam as possible."

    def handle(self, *args, **options):
        print 'Logging in to the API'
        headers = api_login()

        print 'Getting the leaderboards'
        users = get_leaderboards(headers)

        print 'Looping users.'
        for user in filter(lambda obj: obj[2] == 'Steam', users):
            # Is there already a SteamUser with this SteamID?
            print 'Checking for', user[3]
            user, created = SteamUser.objects.get_or_create(
                steam_id=user[3],
            )

        # For each user in the SteamUser table, try to get all of their Rocket
        # League playing friends and load them in too.
        print 'Starting up the SteamAPI'
        steam = WebAPI(key=settings.SOCIAL_AUTH_STEAM_API_KEY)

        users = SteamUser.objects.all()

        print "Working with", users.count(), "users"
        for user in users:
            if not user.username:
                get_username.delay(steam, user)

            get_friends.delay(steam, user.steam_id)
