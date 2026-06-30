from typing import Optional
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import UserProfile, Availability, Booking

User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['id', 'working_start_time', 'working_end_time']


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer()

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'profile']


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Availability
        fields = ['id', 'user', 'date', 'start_time', 'end_time', 'is_booked']


class BookingSerializer(serializers.ModelSerializer):
    availability = AvailabilitySerializer(read_only=True)
    availability_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Booking
        fields = ['id', 'booker', 'booked_user', 'availability', 'availability_id', 'title', 'description', 'created_at']
        read_only_fields = ['booker', 'created_at']

    def create(self, validated_data):
        availability_id = validated_data.pop('availability_id')
        availability = Availability.objects.get(id=availability_id)
        
        if availability.is_booked:
            raise serializers.ValidationError("This slot is already booked")
        
        availability.is_booked = True
        availability.save()
        
        booking = Booking.objects.create(
            availability=availability,
            **validated_data
        )
        return booking


class AvailableSlotSerializer(serializers.Serializer):
    """Serializer for individual availability slots"""
    date: serializers.DateField = serializers.DateField(
        help_text="Date of the availability slot"
    )
    start_time: serializers.TimeField = serializers.TimeField(
        help_text="Start time of the slot"
    )
    end_time: serializers.TimeField = serializers.TimeField(
        help_text="End time of the slot"
    )
    is_available: serializers.BooleanField = serializers.BooleanField(
        help_text="Whether the slot is available for booking"
    )


class SlotSuggestionSerializer(serializers.Serializer):
    """Serializer for suggested booking slots with constraint context"""
    date: serializers.DateField = serializers.DateField(
        help_text="Date of the suggested slot"
    )
    start_time: serializers.TimeField = serializers.TimeField(
        help_text="Start time of the suggested slot"
    )
    end_time: serializers.TimeField = serializers.TimeField(
        help_text="End time of the suggested slot"
    )
    duration_hours: serializers.IntegerField = serializers.IntegerField(
        help_text="Duration of the meeting in hours"
    )
    slot_type: serializers.ChoiceField = serializers.ChoiceField(
        choices=['requested_date', 'alternate_date'],
        help_text="Whether this is on the requested date or an alternate date"
    )
    date_label: serializers.CharField = serializers.CharField(
        help_text="Human-readable label for the date (e.g., 'Requested Date: 2026-07-01')"
    )
    is_available: serializers.BooleanField = serializers.BooleanField(
        help_text="Whether the slot is available (always true in suggestions)"
    )
    constraint_note: serializers.CharField = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Notes about which constraints this slot satisfies"
    )