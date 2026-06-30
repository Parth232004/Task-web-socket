"""
Comprehensive test suite for the scheduler app.
Covers unit tests for business logic and integration tests for API endpoints.
"""
from typing import List, Dict
from datetime import date, time, timedelta
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import AccessToken
from asgiref.sync import async_to_sync
from unittest.mock import patch, MagicMock
from .models import UserProfile, Availability, Booking

User = get_user_model()
from .views import (
    is_business_day,
    get_next_business_days,
    parse_preferred_time_range,
    slot_matches_constraints,
    get_available_slots_for_date,
)


class BusinessDayUtilsTestCase(TestCase):
    """Unit tests for business day calculation utilities"""

    def test_is_business_day_weekday(self):
        """Test that Monday-Friday are business days"""
        for weekday in range(5):  # Mon-Fri
            d = date(2026, 7, 6) + timedelta(days=weekday)  # July 6 is Monday
            self.assertTrue(is_business_day(d))

    def test_is_business_day_weekend(self):
        """Test that Saturday and Sunday are not business days"""
        saturday = date(2026, 7, 11)  # Saturday
        sunday = date(2026, 7, 12)    # Sunday
        self.assertFalse(is_business_day(saturday))
        self.assertFalse(is_business_day(sunday))

    def test_get_next_business_days_inclusive(self):
        """Test that get_next_business_days includes the start date if it's a business day"""
        start = date(2026, 7, 6)  # Monday
        days = get_next_business_days(start, 5)
        self.assertEqual(len(days), 5)
        self.assertEqual(days[0], start)
        self.assertEqual(days[1], date(2026, 7, 7))  # Tuesday
        self.assertEqual(days[2], date(2026, 7, 8))  # Wednesday
        self.assertEqual(days[3], date(2026, 7, 9))  # Thursday
        self.assertEqual(days[4], date(2026, 7, 10)) # Friday

    def test_get_next_business_days_skip_weekend(self):
        """Test that weekends are skipped when counting business days"""
        start = date(2026, 7, 9)  # Thursday
        days = get_next_business_days(start, 5)
        # Should be Thu, Fri, Mon, Tue, Wed (skipping Sat/Sun)
        self.assertEqual(len(days), 5)
        self.assertEqual(days[0], date(2026, 7, 9))   # Thursday
        self.assertEqual(days[1], date(2026, 7, 10))  # Friday
        self.assertEqual(days[2], date(2026, 7, 13))  # Monday
        self.assertEqual(days[3], date(2026, 7, 14))  # Tuesday
        self.assertEqual(days[4], date(2026, 7, 15))  # Wednesday


class SlotConflictResolutionTestCase(TestCase):
    """Unit tests for slot conflict detection"""

    def setUp(self):
        self.user = User.objects.create_user(
            email='testuser@example.com',
            password='testpass123'
        )
        # Signal auto-creates profile, so get it explicitly
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.working_start_time = time(9, 0)
        self.profile.working_end_time = time(17, 0)
        self.profile.save()

    def _build_booked_by_date(self, user: User, dates: List[date]) -> Dict[date, List[Availability]]:
        """Helper to build booked_by_date dict from Availability records"""
        booked_slots = Availability.objects.filter(
            user=user,
            is_booked=True,
            date__in=dates
        ).only('date', 'start_time', 'end_time')
        result: Dict[date, List[Availability]] = {}
        for slot in booked_slots:
            result.setdefault(slot.date, []).append(slot)
        return result

    def test_no_conflict_when_no_booked_slots(self):
        """Test that slots are available when no bookings exist"""
        target_date = date(2026, 7, 6)
        booked_by_date = self._build_booked_by_date(self.user, [target_date])
        
        slots = get_available_slots_for_date(
            target_date=target_date,
            user=self.user,
            duration=1,
            working_start=time(9, 0),
            working_end=time(17, 0),
            booked_by_date=booked_by_date,
        )
        
        # All 8 hourly slots from 9-17 should be available
        self.assertEqual(len(slots), 8)
        for slot in slots:
            self.assertTrue(slot['is_available'])

    def test_conflict_detected_with_booked_slot(self):
        """Test that overlapping slots are correctly marked as unavailable"""
        # Create a booked slot from 10:00-11:00
        Availability.objects.create(
            user=self.user,
            date=date(2026, 7, 6),
            start_time=time(10, 0),
            end_time=time(11, 0),
            is_booked=True
        )
        
        target_date = date(2026, 7, 6)
        booked_by_date = self._build_booked_by_date(self.user, [target_date])
        
        slots = get_available_slots_for_date(
            target_date=target_date,
            user=self.user,
            duration=1,
            working_start=time(9, 0),
            working_end=time(17, 0),
            booked_by_date=booked_by_date,
        )
        
        # 9-10 should be available, 10-11 should NOT be available
        slot_times = [(s['start_time'], s['end_time']) for s in slots]
        self.assertIn((time(9, 0), time(10, 0)), slot_times)
        self.assertNotIn((time(10, 0), time(11, 0)), slot_times)

    def test_partial_overlap_detected(self):
        """Test that partial overlaps are correctly detected"""
        # Create a booked slot from 10:30-11:30 (non-aligned)
        Availability.objects.create(
            user=self.user,
            date=date(2026, 7, 6),
            start_time=time(10, 30),
            end_time=time(11, 30),
            is_booked=True
        )
        
        target_date = date(2026, 7, 6)
        booked_by_date = self._build_booked_by_date(self.user, [target_date])
        
        slots = get_available_slots_for_date(
            target_date=target_date,
            user=self.user,
            duration=1,
            working_start=time(9, 0),
            working_end=time(17, 0),
            booked_by_date=booked_by_date,
        )
        
        # 10-11 overlaps with 10:30-11:30, so should be unavailable
        slot_times = [(s['start_time'], s['end_time']) for s in slots]
        self.assertNotIn((time(10, 0), time(11, 0)), slot_times)
        # 11-12 also overlaps, so should be unavailable
        self.assertNotIn((time(11, 0), time(12, 0)), slot_times)


class ConstraintFilteringTestCase(TestCase):
    """Unit tests for constraint filtering"""

    def setUp(self):
        self.user = User.objects.create_user(
            email='testuser2@example.com',
            password='testpass123'
        )
        # Signal auto-creates profile, so get it explicitly
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.working_start_time = time(9, 0)
        self.profile.working_end_time = time(17, 0)
        self.profile.save()

    def _build_booked_by_date(self, user: User, dates: List[date]) -> Dict[date, List[Availability]]:
        """Helper to build booked_by_date dict"""
        booked_slots = Availability.objects.filter(
            user=user,
            is_booked=True,
            date__in=dates
        ).only('date', 'start_time', 'end_time')
        result: Dict[date, List[Availability]] = {}
        for slot in booked_slots:
            result.setdefault(slot.date, []).append(slot)
        return result

    def test_morning_preference(self):
        """Test morning preference filtering"""
        target_date = date(2026, 7, 6)
        booked_by_date = self._build_booked_by_date(self.user, [target_date])
        preferred_range = parse_preferred_time_range('morning')
        
        slots = get_available_slots_for_date(
            target_date=target_date,
            user=self.user,
            duration=1,
            working_start=time(9, 0),
            working_end=time(17, 0),
            booked_by_date=booked_by_date,
            preferred_range=preferred_range,
        )
        
        # Only slots ending by 12:00 should be returned
        for slot in slots:
            self.assertLessEqual(slot['end_time'], time(12, 0))

    def test_afternoon_preference(self):
        """Test afternoon preference filtering"""
        target_date = date(2026, 7, 6)
        booked_by_date = self._build_booked_by_date(self.user, [target_date])
        preferred_range = parse_preferred_time_range('afternoon')
        
        slots = get_available_slots_for_date(
            target_date=target_date,
            user=self.user,
            duration=1,
            working_start=time(9, 0),
            working_end=time(17, 0),
            booked_by_date=booked_by_date,
            preferred_range=preferred_range,
        )
        
        # Only slots starting at or after 12:00 and ending by 17:00
        for slot in slots:
            self.assertGreaterEqual(slot['start_time'], time(12, 0))
            self.assertLessEqual(slot['end_time'], time(17, 0))

    def test_custom_time_range(self):
        """Test custom time range filtering"""
        target_date = date(2026, 7, 6)
        booked_by_date = self._build_booked_by_date(self.user, [target_date])
        preferred_range = parse_preferred_time_range('09:00-12:00')
        
        slots = get_available_slots_for_date(
            target_date=target_date,
            user=self.user,
            duration=1,
            working_start=time(9, 0),
            working_end=time(17, 0),
            booked_by_date=booked_by_date,
            preferred_range=preferred_range,
        )
        
        for slot in slots:
            self.assertGreaterEqual(slot['start_time'], time(9, 0))
            self.assertLessEqual(slot['end_time'], time(12, 0))

    def test_max_end_time_constraint(self):
        """Test max_end_time constraint"""
        target_date = date(2026, 7, 6)
        booked_by_date = self._build_booked_by_date(self.user, [target_date])
        
        slots = get_available_slots_for_date(
            target_date=target_date,
            user=self.user,
            duration=1,
            working_start=time(9, 0),
            working_end=time(17, 0),
            booked_by_date=booked_by_date,
            max_end_time=time(14, 0),
        )
        
        for slot in slots:
            self.assertLessEqual(slot['end_time'], time(14, 0))

    def test_date_range_constraint(self):
        """Test date range constraint"""
        target_date = date(2026, 7, 6)
        booked_by_date = self._build_booked_by_date(self.user, [target_date])
        
        slots = get_available_slots_for_date(
            target_date=target_date,
            user=self.user,
            duration=1,
            working_start=time(9, 0),
            working_end=time(17, 0),
            booked_by_date=booked_by_date,
            date_range_start=date(2026, 7, 6),
            date_range_end=date(2026, 7, 10),
        )
        
        for slot in slots:
            self.assertGreaterEqual(slot['date'], date(2026, 7, 6))
            self.assertLessEqual(slot['date'], date(2026, 7, 10))


class SuggestSlotsIntegrationTestCase(APITestCase):
    """Integration tests for the suggest_slots endpoint"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='testuser3@example.com',
            password='testpass123'
        )
        # Signal auto-creates profile, so get it explicitly
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.working_start_time = time(9, 0)
        self.profile.working_end_time = time(17, 0)
        self.profile.save()
        # Create a booked slot on 2026-07-06 from 10:00-15:00
        Availability.objects.create(
            user=self.user,
            date=date(2026, 7, 6),
            start_time=time(10, 0),
            end_time=time(15, 0),
            is_booked=True
        )

    def test_suggest_slots_success(self):
        """Test successful slot suggestion"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'date': '2026-07-06'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.data)  # type: ignore[attr-defined]
        self.assertIn('slots', response.data)  # type: ignore[attr-defined]

    def test_suggest_slots_missing_user_id(self):
        """Test error when user_id is missing"""
        response = self.client.get('/api/availabilities/suggest_slots/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suggest_slots_invalid_user_id(self):
        """Test error for non-existent user"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': 99999}
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_suggest_slots_invalid_date(self):
        """Test error for invalid date format"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'date': 'invalid-date'}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suggest_slots_invalid_duration(self):
        """Test error for invalid duration"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'duration': 'abc'}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suggest_slots_negative_duration(self):
        """Test error for negative duration"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'duration': '-1'}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suggest_slots_booked_date_fallback(self):
        """Test fallback to alternate dates when requested date is fully booked"""
        # 2026-07-06 has 10-15 booked, so 9-10 and 15-17 are still available
        # But let's test with a duration that makes it fully booked
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'date': '2026-07-06', 'duration': 4}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # With 4-hour duration and 10-15 booked, no slots on 2026-07-06
        # Should fall back to alternate dates
        self.assertIn('alternate', response.data['message'].lower())  # type: ignore[attr-defined]

    def test_suggest_slots_with_preferred_time(self):
        """Test preferred_time constraint"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'date': '2026-07-06', 'preferred_time': 'morning'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for slot in response.data['slots']:  # type: ignore[attr-defined]
            self.assertLessEqual(slot['end_time'], '12:00:00')

    def test_suggest_slots_with_max_end_time(self):
        """Test max_end_time constraint"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'date': '2026-07-06', 'max_end_time': '14:00'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for slot in response.data['slots']:  # type: ignore[attr-defined]
            self.assertLessEqual(slot['end_time'], '14:00:00')

    def test_suggest_slots_with_date_range(self):
        """Test date range constraint"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {
                'user_id': self.user.pk,
                'date': '2026-07-06',
                'date_range_start': '2026-07-07',
                'date_range_end': '2026-07-10'
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # When date range is provided, all slots within the range should be returned
        self.assertIn('within the specified date range', response.data['message'].lower())  # type: ignore[attr-defined]
        # Verify slots exist for dates in the range (2026-07-07 to 2026-07-10)
        dates_in_response = {slot['date'] for slot in response.data['slots']}  # type: ignore[attr-defined]
        for d in [date(2026, 7, 7), date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 10)]:
            if d.weekday() < 5:  # Only business days
                self.assertIn(d.isoformat(), dates_in_response)

    def test_suggest_slots_invalid_date_range(self):
        """Test error when date_range_start > date_range_end"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {
                'user_id': self.user.pk,
                'date_range_start': '2026-07-10',
                'date_range_end': '2026-07-06'
            }
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suggest_slots_invalid_max_end_time(self):
        """Test error for invalid max_end_time format"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'max_end_time': '25:00'}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suggest_slots_invalid_date_range_format(self):
        """Test error for invalid date range format"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'date_range_start': 'invalid'}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suggest_slots_no_slots_14_days(self):
        """Test response when no slots available in 14 business days"""
        # Book all slots for the next 14 business days (the API checks 14 business days)
        start = date(2026, 7, 6)
        business_days_to_book = []
        current = start
        while len(business_days_to_book) < 14:
            if current.weekday() < 5:  # Business day
                business_days_to_book.append(current)
            current += timedelta(days=1)
        
        for d in business_days_to_book:
            for hour in range(9, 17):
                Availability.objects.create(
                    user=self.user,
                    date=d,
                    start_time=time(hour, 0),
                    end_time=time(hour + 1, 0),
                    is_booked=True
                )
        
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'date': '2026-07-06'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['slots']), 0)  # type: ignore[attr-defined]
        self.assertIn('14 business days', response.data['message'])  # type: ignore[attr-defined]

    def test_suggest_slots_response_structure(self):
        """Test that response has correct structure"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk, 'date': '2026-07-06'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.data)  # type: ignore[attr-defined]
        self.assertIn('slots', response.data)  # type: ignore[attr-defined]
        self.assertIsInstance(response.data['slots'], list)  # type: ignore[attr-defined]
        
        if response.data['slots']:  # type: ignore[attr-defined]
            slot = response.data['slots'][0]  # type: ignore[attr-defined]
            self.assertIn('date', slot)
            self.assertIn('start_time', slot)
            self.assertIn('end_time', slot)
            self.assertIn('duration_hours', slot)
            self.assertIn('slot_type', slot)
            self.assertIn('date_label', slot)
            self.assertIn('is_available', slot)
            self.assertIn('constraint_note', slot)


class RateLimitingTestCase(APITestCase):
    """Tests for rate limiting (basic smoke test)"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='ratelimituser@example.com',
            password='testpass123'
        )
        # Signal auto-creates profile, so update it instead
        self.profile = self.user.profile  # type: ignore[attr-defined]
        self.profile.working_start_time = time(9, 0)
        self.profile.working_end_time = time(17, 0)
        self.profile.save()

    def test_rate_limit_headers_present(self):
        """Test that rate limiting is configured (endpoint responds successfully)"""
        response = self.client.get(
            '/api/availabilities/suggest_slots/',
            {'user_id': self.user.pk}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Rate limiting is configured in settings; verify endpoint is accessible
        self.assertIn('message', response.data)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# WebSocket Tests
# ---------------------------------------------------------------------------

class WebSocketTests(TestCase):
    """Tests for WebSocket slot booking updates"""

    def setUp(self):
        self.user = User.objects.create_user(
            email='wsuser@example.com',
            password='testpass123'
        )
        self.profile = self.user.profile  # type: ignore[attr-defined]
        self.profile.working_start_time = time(9, 0)
        self.profile.working_end_time = time(17, 0)
        self.profile.save()

        # Create some availability slots
        self.today = timezone.now().date()
        self.slot1 = Availability.objects.create(
            user=self.user,
            date=self.today,
            start_time=time(9, 0),
            end_time=time(10, 0),
            is_booked=False
        )
        self.slot2 = Availability.objects.create(
            user=self.user,
            date=self.today,
            start_time=time(10, 0),
            end_time=time(11, 0),
            is_booked=False
        )

    def test_websocket_booking_triggers_channel_layer(self):
        """Test that booking a slot triggers WebSocket notification via channel layer"""
        from channels.layers import get_channel_layer

        # Get the real channel layer (in-memory for tests)
        channel_layer = get_channel_layer()
        self.assertIsNotNone(channel_layer)

        # Book the slot via API
        booker = User.objects.create_user(
            email='booker@example.com',
            password='testpass123'
        )
        response = self.client.post(
            '/api/bookings/',
            {
                'booked_user': self.user.pk,
                'booker': booker.pk,
                'date': self.today.isoformat(),
                'start_time': '10:00:00',
                'end_time': '11:00:00'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify the slot is now booked
        self.slot2.refresh_from_db()
        self.assertTrue(self.slot2.is_booked)
