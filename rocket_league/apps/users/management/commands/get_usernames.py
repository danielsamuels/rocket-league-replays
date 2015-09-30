from django.core.management.base import BaseCommand
from django.conf import settings

from ...models import SteamUser

from rocket_league.apps.users.tasks import get_username

from steam import WebAPI


class Command(BaseCommand):
    help = "Get data from as many people on Steam as possible."

    def handle(self, *args, **options):
        print 'Starting up the SteamAPI'
        steam = WebAPI(key=settings.SOCIAL_AUTH_STEAM_API_KEY)

        users = SteamUser.objects.filter(username='')

        print "Working with", users.count(), "users"
        for x in range(0, users.count(), 100):
            get_username.delay(steam, users[x:x+100])
