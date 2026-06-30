"""
Custom exception handler for the scheduler app.
Returns standardized JSON error responses without exposing internal details.
"""
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom exception handler that returns standardized error responses.
    Logs unhandled exceptions server-side while returning generic messages to clients.
    """
    # Let DRF handle the exception first
    response = exception_handler(exc, context)

    if response is not None and response.data is not None:
        # Standardize DRF exception responses
        detail = response.data.get('detail', 'An error occurred')
        custom_response_data = {
            'error': True,
            'message': str(detail) if detail else 'An error occurred',
            'details': response.data,
        }
        response.data = custom_response_data
        return response

    # Handle unhandled exceptions - log but don't expose details
    logger.error(f'Unhandled exception: {exc}', exc_info=True)
    return Response(
        {
            'error': True,
            'message': 'An unexpected error occurred. Please try again later.',
            'details': {},
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
