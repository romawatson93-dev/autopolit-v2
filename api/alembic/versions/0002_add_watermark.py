"""add watermark_text to clients

Revision ID: 0002_add_watermark
Revises: 0001_create_clients
Create Date: 2025-08-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_add_watermark"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("clients", sa.Column("watermark_text", sa.String(length=200), nullable=True))

def downgrade() -> None:
    op.drop_column("clients", "watermark_text")
