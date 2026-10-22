
def normalize_phone_number(to_number):
    # Remove spaces, just in case
    to_number = to_number.strip().replace(" ", "")

    if to_number.startswith("+255"):
        # Remove the '+' from +255
        formatted_number = to_number[1:]
    elif to_number.startswith("0"):
        # Replace leading 0 with 255
        formatted_number = "255" + to_number[1:]
    else:
        # Leave as is (assumed to already be in 255 format)
        formatted_number = to_number

    return formatted_number