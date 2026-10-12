from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401
from app.config import settings
from app.db import Base

config = context.config


def run():
    with create_engine(settings().database_url, poolclass=pool.NullPool).connect() as connection:
        schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            version_table_schema=schema,
        )
        with context.begin_transaction():
            context.run_migrations()


run()
