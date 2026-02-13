"""添加embedding配置字段到settings表

Revision ID: 4f91a2de77bc
Revises: d887fd1a30a6
Create Date: 2026-02-14 00:11:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f91a2de77bc'
down_revision: Union[str, None] = 'd887fd1a30a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('embedding_mode', sa.String(length=20), nullable=True, server_default='local', comment='Embedding模式: local/api'))
        batch_op.add_column(sa.Column('embedding_provider', sa.String(length=50), nullable=True, server_default='openai', comment='Embedding API提供商'))
        batch_op.add_column(sa.Column('embedding_model', sa.String(length=200), nullable=True, server_default='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', comment='Embedding模型名称'))
        batch_op.add_column(sa.Column('embedding_api_key', sa.String(length=500), nullable=True, comment='Embedding API密钥'))
        batch_op.add_column(sa.Column('embedding_api_base_url', sa.String(length=500), nullable=True, comment='Embedding API地址'))


def downgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('embedding_api_base_url')
        batch_op.drop_column('embedding_api_key')
        batch_op.drop_column('embedding_model')
        batch_op.drop_column('embedding_provider')
        batch_op.drop_column('embedding_mode')
