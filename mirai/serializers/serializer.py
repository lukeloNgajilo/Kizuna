# payments/serializers.py
from rest_framework import serializers
from ..utils.utils import normalize_msisdn, detect_channel

# payments/serializers.py
from mirai.gateways import pick_gateway
from mirai.networks import normalize_msisdn, detect_network

class InitiateCollectionSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    narration = serializers.CharField(max_length=140)
    transaction_ref = serializers.CharField(max_length=100)
    webhook = serializers.URLField(required=False)

    def validate_phone_number(self, value):
        msisdn = normalize_msisdn(value)
        if not msisdn:
            raise serializers.ValidationError("Enter a valid Tanzanian mobile number.")
        if not detect_network(msisdn):
            raise serializers.ValidationError("Unsupported mobile network.")
        return msisdn

    def validate(self, attrs):
        network = detect_network(attrs["phone_number"])
        gateway = pick_gateway(network, attrs["amount"])
        if not gateway:
            raise serializers.ValidationError(
                {"amount": "This amount isn't supported for this network."}
            )
        attrs["network"] = network
        attrs["gateway"] = gateway
        return attrs