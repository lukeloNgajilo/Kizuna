# utils.py
from rest_framework.response import Response


def custom_response(data=None, description="success", status=True, statusCode=200):
    """
    Returns a custom formatted response with fields: status, statusCode, description, data.
    """
    response_data = {
        "status": status,
        "statusCode": statusCode,
        "description": description,  # translated
        "data": data if data is not None else {}
    }
    return Response(response_data, status=statusCode)


def error_custom_response(data=None, description="Failed", error="", status=False, statusCode=400):
    """
    Returns a custom formatted error response with fields: status, statusCode, description, error.
    """
    response_data = {
        "status": status,
        "statusCode": statusCode,
        "description": description,  # translated
        "error": error             # translated
    }
    return Response(response_data, status=statusCode)