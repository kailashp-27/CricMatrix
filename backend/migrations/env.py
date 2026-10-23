from alembic import context
from sqlalchemy import create_engine
from app.config import settings
from app.database import Base
from app import models  # Register model metadata.

database_url = context.config.attributes.get('database_url', settings.database_url)


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    context.configure(url=database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    existing_connection = context.config.attributes.get('connection')
    if existing_connection is not None:
        migrate(existing_connection)
    else:
        with create_engine(database_url).connect() as connection:
            migrate(connection)
