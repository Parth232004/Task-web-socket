from django.db import models
from django.conf import settings
from django.utils import timezone
import datetime


class UserProfile(models.Model):
    """Extended user profile for calendar users"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    working_start_time = models.TimeField(default=datetime.time(9, 0))
    working_end_time = models.TimeField(default=datetime.time(17, 0))

    def __str__(self):
        return f"{self.user.username}'s profile"


class Availability(models.Model):
    """User availability slots (e.g., meeting schedule 10-3)"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='availabilities')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_booked = models.BooleanField(default=False)

    class Meta:
        unique_together = ['user', 'date', 'start_time', 'end_time']
        ordering = ['date', 'start_time']
        indexes = [
            models.Index(fields=['user', 'date', 'is_booked'], name='idx_user_date_booked'),
            models.Index(fields=['user', 'date', 'start_time', 'end_time'], name='idx_user_date_time'),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.date} {self.start_time}-{self.end_time}"


class Booking(models.Model):
    """Booking made by one user with another user"""
    booker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings_made')
    booked_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings_received')
    availability = models.OneToOneField(Availability, on_delete=models.CASCADE, related_name='booking')
    created_at = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=200, default='Meeting')
    description = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.booker.username} -> {self.booked_user.username}: {self.availability.date}"
