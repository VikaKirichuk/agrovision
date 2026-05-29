"""
conftest.py — спільні налаштування pytest для всього пакету тестів.
"""
import pytest
import sys
from unittest.mock import MagicMock

# ── Заглушки лише для бібліотек БД/хмари, яких може не бути ──
STUB_MODULES = [
    'sqlalchemy', 'sqlalchemy.orm', 'sqlalchemy.ext.declarative',
    'sqlalchemy.sql.sqltypes', 'sqlalchemy.dialects',
    'boto3', 'botocore', 'botocore.exceptions',
    'dotenv',
]

for mod in STUB_MODULES:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# botocore.exceptions.ClientError потрібен як реальний клас
from botocore.exceptions import ClientError   # noqa: F401, E402