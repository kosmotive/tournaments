from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('tournaments', '0002_remove_fixture_position_fixture_extras'),
    ]

    operations = [
        migrations.CreateModel(
            name='Participant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='participants', to='auth.User')),
            ],
        ),
        migrations.AddField(
            model_name='participation',
            name='participant',
            field=models.ForeignKey(default=None, on_delete=django.db.models.deletion.CASCADE, related_name='participations', to='tournaments.Participant'),
            preserve_default=False,
        ),
        migrations.AlterUniqueTogether(
            name='participation',
            unique_together={('tournament', 'slot_id'), ('tournament', 'participant'), ('tournament', 'podium_position')},
        ),
        migrations.RemoveField(
            model_name='participation',
            name='user',
        ),
    ]
