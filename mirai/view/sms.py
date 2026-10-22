
from django.http import JsonResponse
import requests
from mirai.utils.response import *
import json
from django.contrib.contenttypes.models import ContentType
from mirai.models import *
from mirai.utils.sms_status_categorization import *
from mirai.utils.formatt import *
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny






class SendSMSAPIView(APIView):

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        to_number = request.data.get("to_number")
        message_text = request.data.get("message_text")
        reference_id = request.data.get("reference_id")

  

        if not to_number.startswith("255"):
            SMS_gateway.objects.create(
                phone_number=to_number,
                message=message_text,
                status="skipped",

            )
            return False
    
        url = settings.SINGLE_SMS_API_URL
        
        payload = json.dumps({
            "from": "SMARTHAVEN",
            "to": to_number,
            "text": message_text,
            "reference": reference_id
        })

        headers = {
            'Authorization': 'Basic bHVrZWxvTmdhamlsbzpOQU92aXZpMTIzIQ==',  
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    

    
        try:
            response = requests.post(url, headers=headers, data=payload, timeout=30)
            response.raise_for_status()
            response_data = response.json()
            
            if 'messages' in response_data and response_data['messages']:
                message_data = response_data['messages'][0]
                status_id = message_data['status']['id']
                status_info = categorize_status(status_id)
                

                # Save response to the database
                print("NGAJILO")
                
            # print(ContentType.objects.filter(id=recipient_object_id).first())
                SMS_gateway.objects.create(
                    phone_number=to_number,
                    message=message_text,
                #    object_id=object_id,
                #   recipient_object_id=recipient_object_id,
                #  recipient_content_type=ContentType.objects.filter(id=recipient_content_type).first(),
                # message_type=message_type,
                    status=status_info['category'],
                    raw_response=response_data
                )
               # print("MIMI")
                if status_info['category'] in ['SUCCESS', 'PENDING']:
                    return  custom_response(description="SMS sent successfully", statusCode=200)
                        
                # Return success response
                return {'statusCode':503, 'description':'try again after some time'}
        except requests.exceptions.RequestException as e:
            print(str(e))
            return {
                'success': False,
                'statusCode': 500,
                'description': f"Network error: {str(e)}"
            }
