\"""create clients table

Revision ID: 0001_create_clients
Revises: 
Create Date: 2025-08-25 00:00:00
\"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001_create_clients'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'clients',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )

def downgrade():
    op.drop_table('clients')
