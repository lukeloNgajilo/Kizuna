import phonenumbers
from rest_framework import serializers
from rest_framework.response import Response
from django.http import JsonResponse
from mirai.utils.custom_exception import IncorrectPhonenumber,IncorrectPhonenumberformat,Password
from rest_framework import viewsets, permissions
import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
import string

def validate_phone_number(value):
 
    try:
        # Always parse assuming Tanzania


        phone = phonenumbers.parse(value, "TZ")
 

        if not phonenumbers.is_valid_number(phone):
            raise IncorrectPhonenumber ()
            

        # ✅ This ensures +255 format is returned
        return phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)

    except phonenumbers.NumberParseException:
        raise IncorrectPhonenumberformat()






class SpecialCharacterValidator:
    def validate(self, password, user=None):

        has_alpha = any(char.isalpha() for char in password)
        has_digit = any(char.isdigit() for char in password)

        if not any(char in string.punctuation for char in password):
            raise Password("Your password must contain at least one special character")
        
        elif len(password) < 8:
            raise Password("Your password length must be 8")
        
        elif not has_alpha:
            raise Password("Password must contains alphabetic or numeric characters")
        elif not has_digit:
            raise Password("Password must contain any alphabetic or numeric characters")
        
    def get_help_text(self):
        return _("Your password must contain at least one special character.")


