from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from scheduler.models import Availability, UserProfile
import datetime


User = get_user_model()


class Command(BaseCommand):
    help = 'Create sample users and availability slots for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            default='user1@example.com',
            help='Email of the user to create availability for.'
        )
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='Date to create availability for (YYYY-MM-DD). Defaults to today if not provided.'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Number of business days to create availability for. Defaults to 1.'
        )

    def handle(self, *args, **options):
        user_email = options['user']
        date_str = options['date']
        num_days = options['days']
        
        # Create user1 (working 9-5, has meeting 10-3)
        user1, created = User.objects.get_or_create(
            email='user1@example.com',
            defaults={'first_name': 'User', 'last_name': 'One'}
        )
        if created:
            user1.set_password('password123')
            user1.save()
        
        # Ensure user1 has a profile with 9-5 working hours
        profile, _ = UserProfile.objects.get_or_create(
            user=user1,
            defaults={
                'working_start_time': datetime.time(9, 0),
                'working_end_time': datetime.time(17, 0)
            }
        )
        
        # Create user2 (another user who wants to book)
        user2, created = User.objects.get_or_create(
            email='user2@example.com',
            defaults={'first_name': 'User', 'last_name': 'Two'}
        )
        if created:
            user2.set_password('password123')
            user2.save()
        
        # Determine the start date
        if date_str:
            try:
                start_date = datetime.date.fromisoformat(date_str)
            except ValueError:
                self.stdout.write(
                    self.style.ERROR(f'Invalid date format: {date_str}. Use YYYY-MM-DD.')
                )
                return
        else:
            start_date = datetime.date.today()
        
        # Generate business days
        business_days = []
        current = start_date
        while len(business_days) < num_days:
            if current.weekday() < 5:  # Monday-Friday
                business_days.append(current)
            current += datetime.timedelta(days=1)
        
        # Create availability slots for each business day (9-5 working hours)
        # Mark 10-3 as booked (meeting schedule)
        for target_date in business_days:
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
        self.stdout.write(f'User1 working hours: 9:00-17:00 (universal, year-round)')
        self.stdout.write(f'User1 meeting schedule: 10:00-15:00 (booked)')
        self.stdout.write(f'Created availability for {len(business_days)} business day(s):')
        for d in business_days:
            self.stdout.write(f'  - {d.isoformat()}')