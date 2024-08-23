from user.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from user.permissions import IsClient
from django.core.files.storage import default_storage
from rest_framework.parsers import MultiPartParser, FormParser
from square.client import Client
import os
from price.models import Price
from .serializers import PaymentLogsSerializer
import uuid
import json
from rest_framework.permissions import IsAuthenticated
from price.serializers import PriceSerializer
from .models import PaymentLogs
from tourplace.models import TourPlace
from datetime import datetime
# Create your views here.

def check_payment_status(payment_id):
    try:
        client = Client(
            access_token=os.environ.get('SQUARE_ACCESS_TOKEN'),
            environment='sandbox'
        )

        response = client.payments.retrieve_payment(payment_id)

        if response.is_success():
            payment_status = response.body['payment']['status']
            _status_ = payment_status
            comment = json.dump(response.body)
            message = ""
            if payment_status == 'PENDING':
                message = "The payment was successfully processed and completed."
            elif payment_status == 'COMPLETED':
                message = "The payment is not yet finalized and is awaiting further action, such as 3D Secure verification or manual review."
            elif payment_status == 'APPROVED':
                message = "The payment has been approved but has not yet been captured."
            elif payment_status == 'CANCELED':
                message = " The payment was canceled before it was completed."
            elif payment_status == 'VOIDED':
                message = "The payment was voided. This can happen if an authorized payment is canceled before it is captured."
            elif payment_status == 'REFUNDED':
                message = "The payment was refunded after it was completed."
            elif payment_status == 'DECLINED':
                message = "The payment was declined by the card issuer or the Square payment gateway."
            elif payment_status == 'FAILED':
                failure_reason = response.body['payment']['failure_reason']
                _status_ = failure_reason
                if failure_reason == 'INSUFFICIENT_FUNDS':
                    message = "The card has insufficient funds."
                elif failure_reason == 'CARD_EXPIRED':
                    message = "The card has expired."
                elif failure_reason == 'CARD_DECLINED':
                    message = "The card was declined by the issuer."
                elif failure_reason == 'INVALID_CARD':
                    message = "The card information provided is invalid."
                elif failure_reason == 'FRAUD_DETECTED':
                    message = "Fraud was detected."
                else:
                    message = "Other reasons not categorized specifically."
            else:
                _status_ = "unknown"
                message = "Unknown reasons not categorized specifically."
            return _status_, comment, message
        elif response.is_error():
            _status_ = "error"
            comment = json.dump(response.errors)
            message = "error"
            return _status_, comment, message
    except Exception as e:
        return "error", "error", str(e)

class PaymentAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)
    
    def post(self, request):
        user = request.user
        token = request.data.get("token")
        price_id = request.data.get("price_id")
        prices = Price.objects.filter(id = price_id)
        if len(prices) == 0:
            return Response({"status": False, "data": "Please input correct price id."}, status=status.HTTP_400_BAD_REQUEST)
        price = prices[0]
        data = {
            "user": user.pk,
            "price": price_id,
            "used": 0,
            "amount": price.price,
            "status": 0,
            "comment": "",
            "message": ""
        }
        try:
            client = Client(
                access_token=os.environ.get("SQUARE_ACCESS_TOKEN"),
                environment="sandbox"
            )
            idempotency_key = str(uuid.uuid4())
            response = client.payments.create_payment({
                "source_id": token,
                "idempotency_key": idempotency_key,
                "amount_money": {
                    "amount": data["amount"],
                    "currency": "USD"
                }
            })
            serializer = {}
            if response.is_success():
                payment_status = response.body['payment']['status']
                data["status"] = payment_status
                data["comment"] = json.dump(response.body)
                if payment_status == 'PENDING':
                    serializer = PaymentLogsSerializer(data = data)
                    data["message"] = "The payment was successfully processed and completed."
                elif payment_status == 'COMPLETED':
                    data["message"] = "The payment is not yet finalized and is awaiting further action, such as 3D Secure verification or manual review."
                    serializer = PaymentLogsSerializer(data = data)
                elif payment_status == 'APPROVED':
                    data["message"] = "The payment has been approved but has not yet been captured."
                elif payment_status == 'CANCELED':
                    data["message"] = " The payment was canceled before it was completed."
                elif payment_status == 'VOIDED':
                    data["message"] = "The payment was voided. This can happen if an authorized payment is canceled before it is captured."
                elif payment_status == 'REFUNDED':
                    data["message"] = "The payment was refunded after it was completed."
                elif payment_status == 'DECLINED':
                    data["message"] = "The payment was declined by the card issuer or the Square payment gateway."
                elif payment_status == 'FAILED':
                    failure_reason = response.body['payment']['failure_reason']
                    data["status"] = failure_reason
                    if failure_reason == 'INSUFFICIENT_FUNDS':
                        data["message"] = "The card has insufficient funds."
                    elif failure_reason == 'CARD_EXPIRED':
                        data["message"] = "The card has expired."
                    elif failure_reason == 'CARD_DECLINED':
                        data["message"] = "The card was declined by the issuer."
                    elif failure_reason == 'INVALID_CARD':
                        data["message"] = "The card information provided is invalid."
                    elif failure_reason == 'FRAUD_DETECTED':
                        data["message"] = "Fraud was detected."
                    else:
                        data["message"] = "Other reasons not categorized specifically."
                else:
                    data["status"] = "unknown"
                    data["message"] = "Unknown reasons not categorized specifically."
                serializer = PaymentLogsSerializer(data = data)
                if serializer.is_valid():
                    serializer.save()
                    data = serializer.data
                    return Response({"status": True, "data": serializer.data}, status=status.HTTP_400_BAD_REQUEST)
            elif response.is_error():
                return Response({"status": False, "data": response.errors}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"status": False, "data": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def get(self, request):
        user = request.user
        paylogs = PaymentLogs.objects.filter(status = 'PENDING')
        for paylog in paylogs:
            comment = json.loads(paylog.comment)
            payment_id = comment.get("payment", {}).get("id")
            if payment_id:
                _status_, comment, message = check_payment_status(payment_id)
                paylog.status = _status_
                paylog.comment = comment
                paylog.message = message
        PaymentLogs.objects.bulk_update(paylogs, ['status', 'comment', 'message'])

        if user.usertype == 1:
            tourplace = TourPlace.objects.first()
        elif user.usertype == 2:
            tourplace = request.query_params.get("tourplace", user.tourplace[0])
        else:
            tourplace = user.tourplace[0]

        prices = Price.objects.filter(tourplace_id=tourplace)

        logs = []
        if user.usertype == 3:
            logs = PaymentLogs.objects.filter(user=user.pk, price__in=prices)
        else:
            logs = PaymentLogs.objects.filter(price__in=prices)

        from_date_str = request.query_params.get('from')
        to_date_str = request.query_params.get('to')
        try:
            # Convert strings to datetime objects for filtering
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d') if from_date_str else None
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d') if to_date_str else None
        except ValueError:
            return Response({"status": False, "message": "Invalid date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
        
        if from_date:
            logs = logs.filter(created_at__gte=from_date)
        if to_date:
            logs = logs.filter(created_at__lte=to_date)
        data = PaymentLogsSerializer(logs, many = True).data
        return Response({"status": True, "data": data}, status=status.HTTP_200_OK)