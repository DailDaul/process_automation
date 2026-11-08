"""Database access and safe, repeatable SQLite initialization for MashUp."""
from pathlib import Path
import re

from flask import current_app, g
from sqlalchemy import create_engine, event

_engines = {}


def get_engine():
    url = current_app.config['DATABASE_URL']
    if url not in _engines:
        connect_args = {'check_same_thread': False} if url.startswith('sqlite') else {}
        engine = create_engine(url, future=True, connect_args=connect_args)
        if url.startswith('sqlite'):
            @event.listens_for(engine, 'connect')
            def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute('PRAGMA foreign_keys=ON')
                cursor.close()
        _engines[url] = engine
    return _engines[url]


def get_db():
    if 'db_conn' not in g:
        g.db_conn = get_engine().connect()
    return g.db_conn


def close_db(error=None):
    connection = g.pop('db_conn', None)
    if connection is not None:
        if connection.in_transaction():
            connection.rollback()
        connection.close()


def _prepare_schema_sql(schema_sql):
    """Remove SQL seed duplicates and make table/index creation repeatable."""
    schema_sql = re.sub(
        r"(?is)^\s*INSERT\s+INTO\s+roles\b.*?;\s*", "",
        schema_sql, flags=re.MULTILINE,
    )
    schema_sql = re.sub(
        r"(?is)^\s*INSERT\s+INTO\s+media_types\b.*?;\s*", "",
        schema_sql, flags=re.MULTILINE,
    )
    schema_sql = re.sub(
        r"(?i)\bCREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS\b)",
        "CREATE TABLE IF NOT EXISTS ", schema_sql,
    )
    schema_sql = re.sub(
        r"(?i)\bCREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS\b)",
        lambda m: "CREATE " + (m.group(1) or "") + "INDEX IF NOT EXISTS ",
        schema_sql,
    )
    schema_sql = re.sub(
        r"(?i)\bCREATE\s+TRIGGER\s+(?!IF\s+NOT\s+EXISTS\b)",
        "CREATE TRIGGER IF NOT EXISTS ", schema_sql,
    )
    schema_sql = re.sub(
        r"(?i)\bCREATE\s+VIEW\s+(?!IF\s+NOT\s+EXISTS\b)",
        "CREATE VIEW IF NOT EXISTS ", schema_sql,
    )
    return schema_sql


def _schema_object_names(schema_sql, object_type):
    pattern = rf"(?i)\bCREATE\s+{object_type}\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)"
    return list(dict.fromkeys(re.findall(pattern, schema_sql)))


def _refresh_views_and_triggers(raw_connection, schema_sql):
    """Refresh derived schema objects without deleting tables or user data."""
    views = _schema_object_names(schema_sql, 'VIEW')
    triggers = _schema_object_names(schema_sql, 'TRIGGER')

    # Views are independent of triggers; drop views first.
    for name in views:
        escaped = name.replace('"', '""')
        raw_connection.execute(f'DROP VIEW IF EXISTS "{escaped}"')
    for name in triggers:
        escaped = name.replace('"', '""')
        raw_connection.execute(f'DROP TRIGGER IF EXISTS "{escaped}"')
    raw_connection.commit()


def _seed_reference_data(connection):
    """Insert reference rows idempotently; demo rows only in an empty database."""
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO roles(role_id, role_name, description) VALUES "
        "(1,'customer','Покупатель'),(2,'employee','Сотрудник магазина')"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO media_types(media_type_id,name,description) VALUES "
        "(1,'CD','Компакт-диск'),(2,'Vinyl','Виниловая пластинка'),(3,'DVD','DVD-диск')"
    )

    existing_data = connection.exec_driver_sql(
        "SELECT "
        "(SELECT COUNT(*) FROM users) + "
        "(SELECT COUNT(*) FROM products) + "
        "(SELECT COUNT(*) FROM companies) + "
        "(SELECT COUNT(*) FROM ensembles) + "
        "(SELECT COUNT(*) FROM musicians)"
    ).scalar_one()
    if existing_data:
        return

    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO companies(company_id,name,country) VALUES "
        "(1,'MashUp Records','Россия'),(2,'Universal Music','США'),(3,'Sony Music','Япония')"
    )
    connection.exec_driver_sql("INSERT OR IGNORE INTO manufacturers(company_id) VALUES (1),(2),(3)")
    connection.exec_driver_sql("INSERT OR IGNORE INTO suppliers(company_id) VALUES (1),(2),(3)")
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO ensembles(ensemble_id,name,ensemble_type,founded_year,description) VALUES "
        "(1,'The Example Band','Рок-группа',2001,'Демонстрационный ансамбль'),"
        "(2,'Nocturne Orchestra','Оркестр',1998,'Демонстрационный оркестр')"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO musicians(musician_id,full_name,country) VALUES "
        "(1,'Александр Примеров','Россия'),(2,'Мария Музыкина','Россия')"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO compositions(composition_id,title,creation_year) VALUES "
        "(1,'First Light',2020),(2,'Ночной этюд',2018),(3,'Open Road',2022)"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO performances(performance_id,composition_id,ensemble_id,recorded_at) VALUES "
        "(1,1,1,'2023-04-10'),(2,2,2,'2022-06-15'),(3,3,1,'2024-02-20')"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO products(product_id,catalog_number,title,media_type_id,manufacturer_company_id,release_date,description,cover_image) VALUES "
        "(1,'MU-CD-001','First Light — The Example Band',1,1,'2023-05-01','Дебютное демонстрационное издание. Атмосферный рок и мелодичные аранжировки.',''),"
        "(2,'MU-VIN-002','Nocturne — Ночной этюд',2,2,'2022-08-12','Оркестровая музыка на виниле. Лимитированное демонстрационное издание.',''),"
        "(3,'MU-CD-003','Open Road',1,3,'2024-03-01','Энергичная подборка композиций для долгих поездок.','')"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO product_performances(product_id,performance_id,disc_number,track_number,track_title,duration_seconds) VALUES "
        "(1,1,1,1,'First Light',228),(2,2,1,1,'Ночной этюд',305),(3,3,1,1,'Open Road',194)"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO product_suppliers(product_id,supplier_company_id,is_preferred) VALUES "
        "(1,1,1),(2,2,1),(3,3,1)"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO product_prices(product_id,retail_price,valid_from) VALUES "
        "(1,149900,'2026-01-01'),(2,289900,'2026-01-01'),(3,119900,'2026-01-01')"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO inventory_movements(product_id,movement_type,quantity,unit_cost,comment) VALUES "
        "(1,'receipt',20,70000,'Начальный демонстрационный остаток'),"
        "(2,'receipt',8,150000,'Начальный демонстрационный остаток'),"
        "(3,'receipt',15,55000,'Начальный демонстрационный остаток')"
    )


def init_database(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        schema_path = Path(app.root_path).parent / 'database' / 'schema.sql'
        if not schema_path.exists():
            schema_path = Path(__file__).resolve().parent.parent / 'database' / 'schema.sql'
        if not schema_path.exists():
            raise FileNotFoundError(f'Не найден файл схемы БД: {schema_path}')

        original_schema_sql = schema_path.read_text(encoding='utf-8-sig')
        schema_sql = _prepare_schema_sql(original_schema_sql)
        raw_connection = get_engine().raw_connection()
        try:
            _refresh_views_and_triggers(raw_connection, schema_sql)
            raw_connection.executescript(schema_sql)
            raw_connection.commit()
        finally:
            raw_connection.close()

        with get_engine().begin() as connection:
            _seed_reference_data(connection)
