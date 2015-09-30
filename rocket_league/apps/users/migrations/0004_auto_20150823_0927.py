# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_auto_20150819_1943'),
    ]

    operations = [
        migrations.RunSQL("DELETE FROM users_steamuser AS P1 USING users_steamuser AS P2 WHERE P1.id > P2.id AND P1.steam_id = P2.steam_id;"),
        migrations.RemoveField(
            model_name='steamuser',
            name='id',
        ),
        migrations.AlterField(
            model_name='steamuser',
            name='steam_id',
            field=models.CharField(max_length=64, serialize=False, primary_key=True),
        ),
    ]
