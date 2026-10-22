

STATUS_CATEGORIES = {
    "SUCCESS": [73],
    "PENDING": [50, 51, 52, 77],
    "RETRYABLE_FAILURE": [74, 78, 80],
    "PERMANENT_FAILURE": list(range(75, 77)) + list(range(53, 74)) + list(range(79, 80)) + list(range(81, 999))
}

STATUS_DESCRIPTIONS = {
    73: "DELIVERED - Successfully delivered",
    50: "PENDING_WAITING_DELIVERY - Awaiting delivery report",
    51: "ENROUTE (SENT) - Sent to next instance",
    52: "PENDING_ACCEPTED - Accepted and processed, ready to send",
    74: "EXPIRED - Unable to deliver in time",
    75: "DELETED - Message deleted",
    76: "UNDELIVERABLE - Unable to deliver (nonexistent number, etc.)",
    77: "ACCEPTED - Accepted and will be sent",
    78: "UNKNOWN - Unknown error",
    79: "REJECTED - Provider blocked",
    80: "SKIPPED - Message skipped",
}

def categorize_status(status_id):
    category = next(
        (key for key, values in STATUS_CATEGORIES.items() if status_id in values), 
        "UNKNOWN"
    )
    
    description = STATUS_DESCRIPTIONS.get(status_id, "Unknown status code")

    return {
        "status_id": status_id,
        "category": category,
        "description": description
    }