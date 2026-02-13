"""添加embedding配置字段到settings表

Revision ID: b3c7c65d9f21
Revises: d4d253e3f4c6
Create Date: 2026-02-14 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c7c65d9f21'
down_revision: Union[str, None] = 'd4d253e3f4c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('settings', sa.Column('embedding_mode', sa.String(length=20), nullable=True, server_default='local', comment='Embedding模式: local/api'))
    op.add_column('settings', sa.Column('embedding_provider', sa.String(length=50), nullable=True, server_default='openai', comment='Embedding API提供商'))
    op.add_column('settings', sa.Column('embedding_model', sa.String(length=200), nullable=True, server_default='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', comment='Embedding模型名称'))
    op.add_column('settings', sa.Column('embedding_api_key', sa.String(length=500), nullable=True, comment='Embedding API密钥'))
    op.add_column('settings', sa.Column('embedding_api_base_url', sa.String(length=500), nullable=True, comment='Embedding API地址'))


def downgrade() -> None:
    op.drop_column('settings', 'embedding_api_base_url')
    op.drop_column('settings', 'embedding_api_key')
    op.drop_column('settings', 'embedding_model')
    op.drop_column('settings', 'embedding_provider')
    op.drop_column('settings', 'embedding_mode')
