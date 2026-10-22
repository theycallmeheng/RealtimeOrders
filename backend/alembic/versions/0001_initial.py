"""Initial InnoDB schema. Only run on a dedicated empty project database."""
from pathlib import Path
from alembic import op
revision = '0001'
down_revision = None

def upgrade():
    sql = (Path(__file__).resolve().parents[3] / 'db/schema.sql').read_text(encoding='utf-8-sig')
    sql = '\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--'))
    for statement in sql.split(';'):
        statement = statement.strip()
        if statement: op.execute(statement)

def downgrade():
    raise RuntimeError('Không tự xóa dữ liệu. Phục hồi bản backup vào database mới.')
