# -*- coding: utf-8 -*-
# Generated by Django 1.11.2 on 2017-06-22 13:48
from __future__ import unicode_literals

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('upload', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='upload',
            name='skipped_keys',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=300), null=True, size=None),
        ),
    ]
