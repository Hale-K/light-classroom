"""Store semester walk configuration with relational slots and rooms."""
from alembic import op

revision = 'w3f5a7b9c1d2'
down_revision = 'v2e4f6a8b0c1'
branch_labels = None
depends_on = None

def upgrade():
    from app.models.gaokao import WalkSchedulingPlan, WalkSchedulingSlot, WalkSchedulingRoom
    for model in (WalkSchedulingPlan, WalkSchedulingSlot, WalkSchedulingRoom):
        model.__table__.create(op.get_bind(), checkfirst=True)

def downgrade():
    for name in ('walk_scheduling_room', 'walk_scheduling_slot', 'walk_scheduling_plan'):
        op.drop_table(name)
