from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


is_sqlite = settings.database_url.startswith('sqlite')
engine = create_engine(settings.database_url, pool_pre_ping=True,
                       connect_args={'check_same_thread': False} if is_sqlite else {},
                       **({} if is_sqlite else {'pool_size': settings.database_pool_size, 'max_overflow': settings.database_max_overflow}))
if engine.dialect.name == 'sqlite':
    @event.listens_for(engine, 'connect')
    def sqlite_foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

SessionLocal = sessionmaker(engine, expire_on_commit=False)


def session_dependency():
    with SessionLocal() as session:
        yield session
