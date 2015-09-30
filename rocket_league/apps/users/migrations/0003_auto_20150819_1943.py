# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_leaguerating'),
    ]

    operations = [
        migrations.CreateModel(
            name='SteamUser',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('steam_id', models.CharField(max_length=64)),
                ('username', models.CharField(max_length=255)),
            ],
        ),
        migrations.AlterField(
            model_name='leaguerating',
            name='user',
            field=models.ForeignKey(blank=True, to=settings.AUTH_USER_MODEL, null=True),
        ),
        migrations.AddField(
            model_name='leaguerating',
            name='steam_user',
            field=models.ForeignKey(blank=True, to='users.SteamUser', null=True),
        ),
    ]
