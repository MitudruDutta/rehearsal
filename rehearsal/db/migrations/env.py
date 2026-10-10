from alembic import context
from sqlalchemy import engine_from_config, pool

from rehearsal.config import settings
from rehearsal.db.models import Base

config = context.config
url = config.get_main_option("sqlalchemy.url") or settings().database_url
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

if context.is_offline_mode():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=Base.metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
