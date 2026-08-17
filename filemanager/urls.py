"""
URL configuration for filemanager project.

The `urlpatterns` list routes URLs to views. For more information please see:
    
https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:

Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from rest_framework import routers
from core.views import FileViewSet, health_check

router = routers.DefaultRouter()
router.register(r'files', FileViewSet, basename='files')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('', include('core.urls')),
    path('api/', include(router.urls)), # DRF API endpoints
    path('health/', health_check, name='health_check'),
    path('', include('django_prometheus.urls')),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
