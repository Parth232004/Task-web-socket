from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from scheduler.models import Availability
import datetime


User = get_user_model()


class Command(BaseCommand):
    help = 'Create sample users and availability slots for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='Date to create availability slots for (YYYY-MM-DD). Defaults to today.'
        )
        parser.add_argument(
            '--user',
            type=str,
            default='user1@example.com',
            help='Email of the user to create availability for.'
        )

    def handle(self, *args, **options):
        date_str = options['date']
        user_email = options['user']
        
        # Parse date or use today
        if date_str:
            try:
                target_date = datetime.date.fromisoformat(date_str)
            except ValueError:
                self.stdout.write(
                    self.style.ERROR(f'Invalid date format: {date_str}. Use YYYY-MM-DD.')
                )
                return
        else:
            target_date = datetime.date.today()
        
        # Create user1 (working 9-5, has meeting 10-3)
        user1, created = User.objects.get_or_create(
            email='user1@example.com',
            defaults={'first_name': 'User', 'last_name': 'One'}
        )
        if created:
            user1.set_password('password123')
            user1.save()
        
        # Create user2 (another user who wants to book)
        user2, created = User.objects.get_or_create(
            email='user2@example.com',
            defaults={'first_name': 'User', 'last_name': 'Two'}
        )
        if created:
            user2.set_password('password123')
            user2.save()
        
        # Create availability slots for user1 (9-5 working hours)
        # Mark 10-3 as booked (meeting schedule)
        for hour in range(9, 17):
            start = datetime.time(hour, 0)
            end = datetime.time(hour + 1, 0)
            
            is_booked = hour >= 10 and hour < 15  # 10-3 is booked
            
            Availability.objects.get_or_create(
                user=user1,
                date=target_date,
                start_time=start,
                end_time=end,
                defaults={'is_booked': is_booked}
            )
        
        self.stdout.write(
            self.style.SUCCESS('Successfully created sample data')
        )
        self.stdout.write(f'User1: {user1.email} (ID: {user1.pk})')
        self.stdout.write(f'User2: {user2.email} (ID: {user2.pk})')
        self.stdout.write(f'Date: {target_date}')
        self.stdout.write('User1 working hours: 9:00-17:00')
        self.stdout.write('User1 meeting schedule: 10:00-15:00 (booked)')
        self.stdout.write(f'Run with --date YYYY-MM-DD to create slots for a specific date')