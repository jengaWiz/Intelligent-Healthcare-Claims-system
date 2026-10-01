from alembic import context

import models
from config.settings import get_settings
from database.session import get_engine

if context.is_offline_mode():
    context.configure(
        url=get_settings().require_database_url(),
        target_metadata=models.Claim.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(
            connection=connection, target_metadata=models.Claim.metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
