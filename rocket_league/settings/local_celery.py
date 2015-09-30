from .local import *

DEBUG = False

BROKER_URL = 'amqp://localhost'
CELERY_RESULT_BACKEND = 'rpc://'
# CELERY_RESULT_BACKEND='djcelery.backends.database:DatabaseBackend',
