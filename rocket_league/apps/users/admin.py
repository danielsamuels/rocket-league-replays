from django.contrib import admin

from .models import LeagueRating, SteamUser


class LeagueRatingAdmin(admin.ModelAdmin):
    list_display = ['user', 'duels', 'doubles', 'standard', 'timestamp']

admin.site.register(LeagueRating, LeagueRatingAdmin)


class SteamUserAdmin(admin.ModelAdmin):
    list_display = ['steam_id', 'username']

admin.site.register(SteamUser, SteamUserAdmin)
