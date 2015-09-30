from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(User)

    def latest_ratings(self):
        ratings = self.user.leaguerating_set.all()[:1]

        if ratings:
            return {
                settings.PLAYLISTS['RankedDuels']: ratings[0].duels,
                settings.PLAYLISTS['RankedDoubles']: ratings[0].doubles,
                settings.PLAYLISTS['RankedStandard']: ratings[0].standard,
            }


class SteamUser(models.Model):

    steam_id = models.CharField(
        primary_key=True,
        max_length=64,
    )

    username = models.CharField(
        max_length=255,
    )


class LeagueRating(models.Model):

    user = models.ForeignKey(
        User,
        blank=True,
        null=True,
    )

    steam_user = models.ForeignKey(
        SteamUser,
        null=True,
        blank=True,
    )

    duels = models.PositiveIntegerField()

    doubles = models.PositiveIntegerField()

    standard = models.PositiveIntegerField()

    timestamp = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ['-timestamp']
