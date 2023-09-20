"""add_lightning_payments

Revision ID: d5e446bf8a1b
Revises: 3e2210c258eb
Create Date: 2023-09-20 10:58:50.145132

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5e446bf8a1b'
down_revision = '3e2210c258eb'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('lightning_invoices',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('invoice', sa.String(), nullable=False),
    sa.Column('payment_hash', sa.String(length=128), nullable=False),
    sa.Column('price', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('paid', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
    sa.PrimaryKeyConstraint('id', 'order_id'),
    sa.UniqueConstraint('id')
    )
    op.create_table('lightning_payment_logs',
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('lightning_invoice_id', sa.Integer(), nullable=False),
    sa.Column('state', sa.Integer(), nullable=False),
    sa.Column('paid_to', sa.String(length=200), nullable=True),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['lightning_invoice_id'], ['lightning_invoices.id'], ),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
    sa.PrimaryKeyConstraint('order_id', 'lightning_invoice_id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('lightning_payment_logs')
    op.drop_table('lightning_invoices')
    # ### end Alembic commands ###
