from rest_framework.views import exception_handler
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated,MethodNotAllowed, ValidationError as DRFValidationErro
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework_simplejwt.exceptions import InvalidToken
from mirai.utils.response import *
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler
from rest_framework.exceptions import (
    NotAuthenticated,
    AuthenticationFailed,
    Throttled,
    MethodNotAllowed,
    NotFound,
)

def custom_exception_handler(exc, context):
    """Custom handler for all API exceptions."""
    response = exception_handler(exc, context)

    if isinstance(exc, NotAuthenticated):
        return error_custom_response(
            description="You must be logged in to access this resource",
            statusCode=401,
        )

    # JWT login token expired or tampered with
    if isinstance(exc, InvalidToken):
        return error_custom_response(
            description="Your login session is invalid. Please sign in again",
            statusCode=401,
        )

    # Any other auth failure, e.g. payment key problems: show the real reason
    if isinstance(exc, AuthenticationFailed):
        return error_custom_response(
            description=str(exc.detail),
            statusCode=401,
        )

    if isinstance(exc, Throttled):
        wait = int(exc.wait) if exc.wait else 60
        return error_custom_response(
            description=f"Too many requests. Try again after {wait} seconds.",
            statusCode=429,
        )

    if isinstance(exc, MethodNotAllowed):
        return error_custom_response(
            description="Method not allowed on this endpoint.",
            statusCode=405,
        )

    if isinstance(exc, NotFound):
        return error_custom_response(
            description="The requested resource was not found.",
            statusCode=404,
        )

    return response


def get_first_error_message(serializer_errors):
    """
    Takes DRF serializer.errors and returns a clean string:
    'Field Name: Error Message'
    """
    if not serializer_errors:
        return "Unknown validation error"
    field = next(iter(serializer_errors))
    errors = serializer_errors[field]
    message = errors[0] if isinstance(errors, list) else str(errors)
    clean_field = field.replace("_", " ").capitalize()
    return f"{clean_field}: {message}"