"""Independent relational time structures for each grade semester."""
from alembic import op

revision = 'x4a6b8c0d2e4'
down_revision = 'w3f5a7b9c1d2'
branch_labels = None
depends_on = None


def upgrade():
    from app.models.scheduling_grid import SchedulingGridPlan, SchedulingGridDay, SchedulingGridSubject, SchedulingGridSlot
    from app.services.scheduling.grid_migration import migrate_legacy_grids
    connection = op.get_bind()
    for model in (SchedulingGridPlan, SchedulingGridDay, SchedulingGridSubject, SchedulingGridSlot):
        model.__table__.create(connection, checkfirst=True)
    result = migrate_legacy_grids(connection)
    if result['skipped']:
        raise RuntimeError(f"Invalid legacy grids require repair: {result['skipped']}")


def downgrade():
    for name in ('scheduling_grid_slot', 'scheduling_grid_subject', 'scheduling_grid_day', 'scheduling_grid_plan'):
        op.drop_table(name)
