from django.urls import path
from mirai.view.Tembo import InitiateCollection
from mirai.view.TemboCallback import TemboCallback



urlpatterns = [
    path("collections/", InitiateCollection.as_view(), name="initiate-collection"),
    path("callbacks/tembo/<str:token>/", TemboCallback.as_view(), name="tembo-callback")
]