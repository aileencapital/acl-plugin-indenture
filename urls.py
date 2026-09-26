"""
URL configuration for the indenture extractor mini-app.

The framework mounts these patterns at /utilities/indenture/ (beta tier).
All internal references use the namespaced form indenture:<name>.
"""

from django.urls import path

from . import views

app_name = "indenture"

urlpatterns = [
    path("", views.index, name="index"),
    path("extract/", views.extract, name="extract"),
    path("download/<str:run_id>/", views.download_csv, name="download"),
    path("presets/", views.presets_list, name="presets_list"),
    path("presets/<str:set_id>/", views.presets_detail, name="presets_detail"),
    path("history/", views.history, name="history"),
    path("history/<str:run_id>/", views.history_detail, name="history_detail"),
]
