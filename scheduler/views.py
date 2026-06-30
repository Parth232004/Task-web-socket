from typing import Optional, Dict, List, Tuple
from pathlib import Path
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Q, Prefetch
from django.utils import timezone
from django.http import HttpResponse
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import datetime
from .models import UserProfile, Availability, Booking

User = get_user_model()
from .serializers import (
    UserSerializer, UserProfileSerializer,
    AvailabilitySerializer, BookingSerializer,
    AvailableSlotSerializer, SlotSuggestionSerializer
)


def suggest_slots_frontend(request):
    """Serve the lightweight frontend for manual testing"""
    frontend_path = Path(__file__).resolve().parent.parent / 'suggest_slots.html'
    with open(frontend_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return HttpResponse(content, content_type='text/html')


# ---------------------------------------------------------------------------
# Module-level utility functions (extracted for testability and reuse)
# ---------------------------------------------------------------------------

def is_business_day(d: datetime.date) -> bool:
    """Check if a date is a business day (Monday-Friday)."""
    return d.weekday() < 5  # Monday=0, Friday=4


def get_next_business_days(start_date: datetime.date, count: int) -> List[datetime.date]:
    """
    Get the next 'count' business days starting from start_date (inclusive).
    Skips weekends (Saturday and Sunday).
    """
    days: List[datetime.date] = []
    current: datetime.date = start_date
    while len(days) < count:
        if is_business_day(current):
            days.append(current)
        current += datetime.timedelta(days=1)
    return days


def parse_preferred_time_range(preferred_time: Optional[str]) -> Optional[Tuple[datetime.time, datetime.time]]:
    """
    Parse a preferred_time string into a (start_time, end_time) tuple.
    Supported formats:
        - 'morning' -> (00:00, 12:00)
        - 'afternoon' -> (12:00, 17:00)
        - 'evening' -> (17:00, 23:59)
        - 'HH:MM-HH:MM' -> custom range
    Returns None if the input is empty or invalid.
    """
    if not preferred_time:
        return None

    pt = preferred_time.strip().lower()
    if pt == 'morning':
        return (datetime.time(0, 0), datetime.time(12, 0))
    elif pt == 'afternoon':
        return (datetime.time(12, 0), datetime.time(17, 0))
    elif pt == 'evening':
        return (datetime.time(17, 0), datetime.time(23, 59))
    elif '-' in pt:
        parts = pt.split('-')
        if len(parts) == 2:
            try:
                start = datetime.time.fromisoformat(parts[0].strip())
                end = datetime.time.fromisoformat(parts[1].strip())
                return (start, end)
            except ValueError:
                pass
    return None


def slot_matches_constraints(
    slot_start: datetime.time,
    slot_end: datetime.time,
    target_date: datetime.date,
    *,
    date_range_start: Optional[datetime.date] = None,
    date_range_end: Optional[datetime.date] = None,
    max_end_time: Optional[datetime.time] = None,
    preferred_range: Optional[Tuple[datetime.time, datetime.time]] = None,
) -> bool:
    """
    Check if a proposed slot satisfies all user-provided constraints.
    """
    # Date range constraint
    if date_range_start and target_date < date_range_start:
        return False
    if date_range_end and target_date > date_range_end:
        return False
    # Max end time constraint
    if max_end_time and slot_end > max_end_time:
        return False
    # Preferred time constraint (slot must be fully within the preferred range)
    if preferred_range:
        pref_start, pref_end = preferred_range
        if not (slot_start >= pref_start and slot_end <= pref_end):
            return False
    return True


def get_available_slots_for_date(
    target_date: datetime.date,
    user: User,
    duration: int,
    working_start: datetime.time,
    working_end: datetime.time,
    booked_by_date: Dict[datetime.date, List[Availability]],
    *,
    date_range_start: Optional[datetime.date] = None,
    date_range_end: Optional[datetime.date] = None,
    max_end_time: Optional[datetime.time] = None,
    preferred_time: Optional[str] = None,
    preferred_range: Optional[Tuple[datetime.time, datetime.time]] = None,
    requested_date: Optional[datetime.date] = None,
) -> List[dict]:
    """
    Compute available slots for a single date, filtered by constraints.
    Returns a list of slot dicts ready for serialization.
    """
    slots: List[dict] = []
    current_time = datetime.datetime.combine(target_date, working_start)
    end_datetime = datetime.datetime.combine(target_date, working_end)
    day_booked_slots: List[Availability] = booked_by_date.get(target_date, [])

    while current_time < end_datetime:
        slot_start: datetime.time = current_time.time()
        slot_end: datetime.time = (current_time + datetime.timedelta(hours=duration)).time()

        if slot_end <= working_end:
            # Check overlap with booked slots (O(k) where k = booked slots for this date)
            is_available: bool = True
            for booked in day_booked_slots:
                if (slot_start < booked.end_time and slot_end > booked.start_time):
                    is_available = False
                    break

            if is_available and slot_matches_constraints(
                slot_start, slot_end, target_date,
                date_range_start=date_range_start,
                date_range_end=date_range_end,
                max_end_time=max_end_time,
                preferred_range=preferred_range,
            ):
                constraint_notes: List[str] = []
                if preferred_time:
                    constraint_notes.append(f"matches preferred time: {preferred_time}")
                if max_end_time:
                    max_end_time_str = max_end_time.strftime('%H:%M')
                    constraint_notes.append(f"ends by {max_end_time_str}")
                if date_range_start or date_range_end:
                    range_str = ""
                    if date_range_start and date_range_end:
                        range_str = f"{date_range_start.isoformat()} to {date_range_end.isoformat()}"
                    elif date_range_start:
                        range_str = f"from {date_range_start.isoformat()}"
                    else:
                        # date_range_end is guaranteed non-None here due to the outer if condition
                        range_str = f"until {date_range_end.isoformat()}"  # type: ignore[union-attr]
                    constraint_notes.append(f"within date range: {range_str}")

                slots.append({
                    'date': target_date,
                    'start_time': slot_start,
                    'end_time': slot_end,
                    'duration_hours': duration,
                    'slot_type': 'requested_date' if target_date == requested_date else 'alternate_date',
                    'date_label': (
                        f"Requested Date: {target_date.isoformat()}"
                        if target_date == requested_date
                        else f"Alternate Date: {target_date.isoformat()}"
                    ),
                    'is_available': True,
                    'constraint_note': "; ".join(constraint_notes) if constraint_notes else ""
                })

        current_time += datetime.timedelta(hours=1)

    return slots


# ---------------------------------------------------------------------------
# ViewSets
# ---------------------------------------------------------------------------

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer


class AvailabilityViewSet(viewsets.ModelViewSet):
    queryset = Availability.objects.all()
    serializer_class = AvailabilitySerializer

    @action(detail=False, methods=['get'])
    def available_slots(self, request):
        """
        Get available slots for a user between their working hours.
        Query params: user_id, date (optional, defaults to today)
        """
        user_id = request.query_params.get('user_id')
        date_str = request.query_params.get('date', timezone.now().date().isoformat())

        if not user_id:
            return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(id=user_id)
            date = datetime.date.fromisoformat(date_str)
        except (User.DoesNotExist, ValueError):
            return Response({'error': 'Invalid user_id or date'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            profile = UserProfile.objects.get(user=user)
        except UserProfile.DoesNotExist:
            return Response(
                {'error': 'User profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        working_start = profile.working_start_time
        working_end = profile.working_end_time

        # Get all booked slots for the user on this date
        booked_slots = Availability.objects.filter(
            user=user,
            date=date,
            is_booked=True
        )

        # Generate all possible slots (hourly) within working hours
        available_slots = []
        current_time = datetime.datetime.combine(date, working_start)
        end_datetime = datetime.datetime.combine(date, working_end)

        while current_time < end_datetime:
            slot_start = current_time.time()
            slot_end = (current_time + datetime.timedelta(hours=1)).time()

            if slot_end <= working_end:
                is_booked = booked_slots.filter(
                    start_time=slot_start,
                    end_time=slot_end
                ).exists()

                available_slots.append({
                    'date': date,
                    'start_time': slot_start,
                    'end_time': slot_end,
                    'is_available': not is_booked
                })

            current_time += datetime.timedelta(hours=1)

        serializer = AvailableSlotSerializer(available_slots, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], throttle_classes=[AnonRateThrottle, UserRateThrottle])
    def suggest_slots(self, request):
        """
        Suggest available slots for booking.
        Checks requested date and next 14 business days.
        If no slots on requested date, suggests next 3 earliest alternate dates.
        Query params:
            user_id (required): ID of the user to check availability for
            date (optional, defaults to today): Requested date in YYYY-MM-DD format
            duration (optional, in hours, default 1): Meeting duration
            preferred_time (optional: "morning", "afternoon", "evening", or "HH:MM-HH:MM")
            max_end_time (optional: "HH:MM"): Latest acceptable end time
            date_range_start (optional: "YYYY-MM-DD"): Start of acceptable date range
            date_range_end (optional: "YYYY-MM-DD"): End of acceptable date range
        """
        # --- Input Validation ---
        user_id: Optional[str] = request.query_params.get('user_id')
        date_str: Optional[str] = request.query_params.get('date')
        duration_str: Optional[str] = request.query_params.get('duration', '1')
        preferred_time: Optional[str] = request.query_params.get('preferred_time')
        max_end_time_str: Optional[str] = request.query_params.get('max_end_time')
        date_range_start_str: Optional[str] = request.query_params.get('date_range_start')
        date_range_end_str: Optional[str] = request.query_params.get('date_range_end')

        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate duration is a positive integer
        try:
            duration_val: int = int(duration_str) if duration_str else 1
            if duration_val <= 0:
                raise ValueError('Duration must be positive')
            duration: int = duration_val
        except (ValueError, TypeError):
            return Response(
                {'error': 'duration must be a positive integer'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate user exists
        try:
            user: User = User.objects.select_related('profile').get(id=user_id)
        except (User.DoesNotExist, ValueError):
            return Response(
                {'error': 'Invalid user_id'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate requested date
        try:
            requested_date: datetime.date = (
                datetime.date.fromisoformat(date_str) if date_str else timezone.now().date()
            )
        except ValueError:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate user profile exists
        try:
            profile: UserProfile = UserProfile.objects.get(user=user)
        except UserProfile.DoesNotExist:
            return Response(
                {'error': 'User profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        working_start: datetime.time = profile.working_start_time
        working_end: datetime.time = profile.working_end_time

        # --- Parse Constraint Filters ---
        max_end_time: Optional[datetime.time] = None
        if max_end_time_str:
            try:
                max_end_time = datetime.time.fromisoformat(max_end_time_str)
            except ValueError:
                return Response(
                    {'error': 'Invalid max_end_time format. Use HH:MM'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        date_range_start: Optional[datetime.date] = None
        date_range_end: Optional[datetime.date] = None
        if date_range_start_str:
            try:
                date_range_start = datetime.date.fromisoformat(date_range_start_str)
            except ValueError:
                return Response(
                    {'error': 'Invalid date_range_start format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        if date_range_end_str:
            try:
                date_range_end = datetime.date.fromisoformat(date_range_end_str)
            except ValueError:
                return Response(
                    {'error': 'Invalid date_range_end format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Validate date range logic
        if date_range_start and date_range_end and date_range_start > date_range_end:
            return Response(
                {'error': 'date_range_start must be before or equal to date_range_end'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Determine search window ---
        # When a date range is provided, search the full range.
        # Otherwise, use requested date + 14 business days (original behavior).
        if date_range_start or date_range_end:
            range_start: datetime.date = date_range_start if date_range_start else requested_date
            range_end: datetime.date = date_range_end if date_range_end else (requested_date + datetime.timedelta(days=14))
            # Collect all business days within the range
            all_business_days = []
            current = range_start
            while current <= range_end:
                if is_business_day(current):
                    all_business_days.append(current)
                current += datetime.timedelta(days=1)
        else:
            all_business_days = get_next_business_days(requested_date, 14)

        # --- Pre-fetch Booked Slots (O(1) query per date instead of O(n)) ---
        # Single query to fetch all booked slots for these dates, grouped by date
        booked_slots_qs = Availability.objects.filter(
            user=user,
            is_booked=True,
            date__in=all_business_days
        ).only('date', 'start_time', 'end_time')

        # Group booked slots by date for O(1) lookup
        booked_by_date: Dict[datetime.date, List[Availability]] = {}
        for slot in booked_slots_qs:
            booked_by_date.setdefault(slot.date, []).append(slot)

        # --- Parse Preferred Time ---
        preferred_range: Optional[Tuple[datetime.time, datetime.time]] = parse_preferred_time_range(preferred_time)

        # --- Collect slots from all business days ---
        requested_date_slots: List[dict] = []
        alternate_date_slots: List[dict] = []

        for bd in all_business_days:
            slots = get_available_slots_for_date(
                target_date=bd,
                user=user,
                duration=duration,
                working_start=working_start,
                working_end=working_end,
                booked_by_date=booked_by_date,
                date_range_start=date_range_start,
                date_range_end=date_range_end,
                max_end_time=max_end_time,
                preferred_time=preferred_time,
                preferred_range=preferred_range,
                requested_date=requested_date,
            )
            if bd == requested_date:
                requested_date_slots.extend(slots)
            else:
                alternate_date_slots.extend(slots)

        # --- Determine response ---
        if date_range_start or date_range_end:
            # When a date range is provided, return ALL slots within the range
            result_slots = requested_date_slots + alternate_date_slots
            if result_slots:
                message = f"Found {len(result_slots)} available slot(s) within the specified date range."
            else:
                message = (
                    f"No slots are available in the specified date range ({date_range_start_str or requested_date.isoformat()} to {date_range_end_str or (requested_date + datetime.timedelta(days=14)).isoformat()}). "
                    "Recommendation: Please adjust your constraints (e.g., preferred time, duration, or date range) or request a later date."
                )
        elif requested_date_slots:
            result_slots: List[dict] = requested_date_slots
            message: str = f"Found {len(result_slots)} available slot(s) on the requested date."
        elif alternate_date_slots:
            # Group alternate slots by date and take next 3 earliest dates
            from collections import defaultdict
            by_date: Dict[datetime.date, List[dict]] = defaultdict(list)
            for slot in alternate_date_slots:
                by_date[slot['date']].append(slot)

            sorted_dates: List[datetime.date] = sorted(by_date.keys())
            top_3_dates: List[datetime.date] = sorted_dates[:3]
            result_slots = []
            for d in top_3_dates:
                result_slots.extend(by_date[d])

            message = (
                f"No slots available on the requested date ({requested_date.isoformat()}). "
                f"Showing next 3 earliest alternate dates with available slots."
            )
        else:
            # No slots in 14 business days
            message = (
                f"No slots are available in the next 14 business days (through {all_business_days[-1].isoformat()}). "
                "Recommendation: Please adjust your constraints (e.g., preferred time, duration, or date range) or request a later date."
            )
            result_slots = []

        response_data = {
            'message': message,
            'slots': SlotSuggestionSerializer(result_slots, many=True).data
        }
        return Response(response_data)


class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer

    def create(self, request, *args, **kwargs):
        """Create a booking for an available slot"""
        user_id = request.data.get('booked_user')
        booker_id = request.data.get('booker')
        if not booker_id:
            return Response(
                {'error': 'booker is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        date = request.data.get('date')
        start_time = request.data.get('start_time')
        end_time = request.data.get('end_time')

        if not all([user_id, date, start_time, end_time]):
            return Response(
                {'error': 'booked_user, date, start_time, and end_time are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(id=user_id)
            booker = User.objects.get(id=booker_id)
            date = datetime.date.fromisoformat(date)
            start_time = datetime.time.fromisoformat(start_time)
            end_time = datetime.time.fromisoformat(end_time)
        except (User.DoesNotExist, ValueError):
            return Response({'error': 'Invalid parameters'}, status=status.HTTP_400_BAD_REQUEST)

        # Check if slot exists and is available (with transaction to prevent race conditions)
        from django.db import transaction
        try:
            with transaction.atomic():
                availability = Availability.objects.select_for_update().get(
                    user=user,
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                    is_booked=False
                )
        except Availability.DoesNotExist:
            return Response(
                {'error': 'Slot not available. Use suggest_slots to find available slots.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create booking
        try:
            booking = Booking.objects.create(
                booker=booker,
                booked_user=user,
                availability=availability,
                title=request.data.get('title', 'Meeting'),
                description=request.data.get('description', '')
            )
        except IntegrityError:
            return Response(
                {'error': 'This slot was just booked by someone else. Please try another slot.'},
                status=status.HTTP_409_CONFLICT
            )

        availability.is_booked = True
        availability.save()
        
        # Double-check that the booking was created successfully
        if not Booking.objects.filter(availability=availability).exists():
            return Response(
                {'error': 'Failed to create booking. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Send WebSocket notification to all users viewing this date
        channel_layer = get_channel_layer()
        if channel_layer:
            booking_data = {
                'id': booking.id,
                'title': booking.title,
                'description': booking.description,
                'date': date.isoformat(),
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'booker_id': booker.id,
                'booker_email': booker.email,
                'booker_name': booker.get_full_name() or booker.email,
                'booked_user_id': user.id,
                'booked_user_email': user.email,
                'booked_user_name': user.get_full_name() or user.email,
                'created_at': booking.created_at.isoformat(),
            }
            
            # Broadcast to date-specific room
            async_to_sync(channel_layer.group_send)(
                f'slots_{date.isoformat()}',
                {
                    'type': 'booking_created',
                    'booking': booking_data
                }
            )
            
            # Broadcast to both users' personal rooms
            async_to_sync(channel_layer.group_send)(
                f'user_{booker.id}',
                {
                    'type': 'booking_created',
                    'booking': booking_data
                }
            )
            async_to_sync(channel_layer.group_send)(
                f'user_{user.id}',
                {
                    'type': 'booking_created',
                    'booking': booking_data
                }
            )

        serializer = BookingSerializer(booking)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """Cancel a booking and broadcast cancellation"""
        instance = self.get_object()
        
        # Get booking details before deletion for WebSocket broadcast
        booking_id = instance.id
        availability = instance.availability
        date_str = availability.date.isoformat()
        start_time = availability.start_time.isoformat()
        end_time = availability.end_time.isoformat()
        booked_user_id = availability.user.id
        
        # Free up the slot
        availability.is_booked = False
        availability.save()
        
        # Delete the booking
        instance.delete()
        
        # Send WebSocket notification
        channel_layer = get_channel_layer()
        if channel_layer:
            # Broadcast to date-specific room
            async_to_sync(channel_layer.group_send)(
                f'slots_{date_str}',
                {
                    'type': 'booking_cancelled',
                    'booking_id': booking_id,
                    'date': date_str,
                    'start_time': start_time,
                    'end_time': end_time,
                }
            )
            
            # Broadcast to booked user's personal room
            async_to_sync(channel_layer.group_send)(
                f'user_{booked_user_id}',
                {
                    'type': 'booking_cancelled',
                    'booking_id': booking_id,
                    'date': date_str,
                    'start_time': start_time,
                    'end_time': end_time,
                }
            )
        
        return Response(status=status.HTTP_204_NO_CONTENT)
