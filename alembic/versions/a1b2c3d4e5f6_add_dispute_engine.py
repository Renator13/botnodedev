"""Add dispute engine tables and escrow.dispute_reason column.

Revision ID: a1b2c3d4e5f6
Revises: 769e7dbf88bf
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a1b2c3d4e5f6'
down_revision = '769e7dbf88bf'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dispute_rules_log',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('escrow_id', sa.String(), nullable=False),
        sa.Column('rule_applied', sa.String(50), nullable=False),
        sa.Column('rule_details', sa.JSON(), nullable=True),
        sa.Column('action_taken', sa.String(30), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.ForeignKeyConstraint(['escrow_id'], ['escrows.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dispute_rules_log_task_id', 'dispute_rules_log', ['task_id'])
    op.create_index('ix_dispute_rules_log_escrow_id', 'dispute_rules_log', ['escrow_id'])
    op.create_index('ix_dispute_rules_log_rule_applied', 'dispute_rules_log', ['rule_applied'])
    op.create_index('ix_dispute_rules_log_created_at', 'dispute_rules_log', ['created_at'])

    op.add_column('escrows', sa.Column('dispute_reason', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('escrows', 'dispute_reason')
    op.drop_index('ix_dispute_rules_log_created_at', 'dispute_rules_log')
    op.drop_index('ix_dispute_rules_log_rule_applied', 'dispute_rules_log')
    op.drop_index('ix_dispute_rules_log_escrow_id', 'dispute_rules_log')
    op.drop_index('ix_dispute_rules_log_task_id', 'dispute_rules_log')
    op.drop_table('dispute_rules_log')
