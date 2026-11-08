import sys
from pathlib import Path
from sqlalchemy import create_engine, text
root=Path(__file__).resolve().parents[1]
db=root/'instance'/'mashup.db'
if len(sys.argv)!=2:
    raise SystemExit('Использование: python scripts/promote_employee.py ЛОГИН')
if not db.exists(): raise SystemExit('Сначала запусти приложение, чтобы создать базу.')
engine=create_engine(f'sqlite:///{db}')
with engine.begin() as conn:
    result=conn.execute(text("UPDATE users SET role_id=(SELECT role_id FROM roles WHERE role_name='employee') WHERE login=:login COLLATE NOCASE"),{'login':sys.argv[1]})
    if result.rowcount!=1: raise SystemExit('Пользователь с таким логином не найден.')
print('Роль сотрудника назначена. Выйди из аккаунта и войди снова.')
