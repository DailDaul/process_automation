-- MashUp: схема базы данных SQLite
-- Версия: 1.0
-- Назначение: локальное веб-приложение музыкального магазина.
--
-- ВАЖНО:
-- 1. При каждом соединении приложения с SQLite необходимо выполнять
--    PRAGMA foreign_keys = ON (одного включения в этом файле недостаточно).
-- 2. Денежные значения хранятся целыми числами в копейках.
-- 3. Даты событий (release_date, valid_from и т. п.) хранятся в формате YYYY-MM-DD.
--    Временные метки created_at/completed_at хранятся в формате YYYY-MM-DD HH:MM:SS.
-- 4. Строгую календарную проверку дат приложение дополнительно выполняет в Python.
-- 5. Остаток товара вычисляется по журналу inventory_movements, а не хранится в products.
-- 6. Продажи вычисляются по завершённым заказам и движениям типа sale.
-- 7. Физические экземпляры одного издания отдельно не регистрируются:
--    products описывает издание, а количество экземпляров определяется складскими движениями.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

BEGIN TRANSACTION;

-- ============================================================
-- 1. ПОЛЬЗОВАТЕЛИ И РОЛИ
-- ============================================================

CREATE TABLE roles (
    role_id INTEGER PRIMARY KEY,
    role_name TEXT NOT NULL UNIQUE
        CHECK (role_name IN ('customer', 'employee')),
    description TEXT
);

CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    role_id INTEGER NOT NULL,
    username TEXT NOT NULL
        CHECK (length(trim(username)) BETWEEN 1 AND 100),
    login TEXT NOT NULL COLLATE NOCASE UNIQUE
        CHECK (length(trim(login)) BETWEEN 3 AND 50),
    phone TEXT NOT NULL UNIQUE
        CHECK (length(trim(phone)) BETWEEN 5 AND 30),
    email TEXT COLLATE NOCASE UNIQUE
        CHECK (email IS NULL OR length(trim(email)) BETWEEN 5 AND 254),
    password_hash TEXT NOT NULL
        CHECK (length(password_hash) > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    FOREIGN KEY (role_id) REFERENCES roles(role_id) ON DELETE RESTRICT
);

CREATE INDEX idx_users_role_id ON users(role_id);

-- ============================================================
-- 2. МУЗЫКАНТЫ, АНСАМБЛИ И МУЗЫКАЛЬНЫЕ ПРОИЗВЕДЕНИЯ
-- ============================================================

CREATE TABLE musicians (
    musician_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL
        CHECK (length(trim(full_name)) BETWEEN 1 AND 200),
    birth_date TEXT
        CHECK (birth_date IS NULL OR
               (length(birth_date) = 10 AND birth_date GLOB '????-??-??')),
    death_date TEXT
        CHECK (death_date IS NULL OR
               (length(death_date) = 10 AND death_date GLOB '????-??-??')),
    country TEXT
        CHECK (country IS NULL OR length(country) <= 100),
    biography TEXT,
    CHECK (birth_date IS NULL OR death_date IS NULL OR death_date >= birth_date)
);

CREATE TABLE instruments (
    instrument_id INTEGER PRIMARY KEY,
    instrument_name TEXT NOT NULL UNIQUE
        CHECK (length(trim(instrument_name)) BETWEEN 1 AND 100)
);

CREATE TABLE musician_instruments (
    musician_id INTEGER NOT NULL,
    instrument_id INTEGER NOT NULL,
    PRIMARY KEY (musician_id, instrument_id),
    FOREIGN KEY (musician_id) REFERENCES musicians(musician_id) ON DELETE CASCADE,
    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id) ON DELETE RESTRICT
);

CREATE INDEX idx_musician_instruments_instrument
    ON musician_instruments(instrument_id);

CREATE TABLE ensembles (
    ensemble_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
        CHECK (length(trim(name)) BETWEEN 1 AND 200),
    ensemble_type TEXT NOT NULL
        CHECK (length(trim(ensemble_type)) BETWEEN 1 AND 100),
    founded_year INTEGER
        CHECK (founded_year IS NULL OR founded_year BETWEEN 1000 AND 2100),
    disbanded_year INTEGER
        CHECK (disbanded_year IS NULL OR disbanded_year BETWEEN 1000 AND 2100),
    description TEXT,
    CHECK (founded_year IS NULL OR disbanded_year IS NULL
           OR disbanded_year >= founded_year)
);

CREATE TABLE ensemble_members (
    ensemble_member_id INTEGER PRIMARY KEY,
    ensemble_id INTEGER NOT NULL,
    musician_id INTEGER NOT NULL,
    member_role TEXT
        CHECK (member_role IS NULL OR length(member_role) <= 100),
    joined_at TEXT
        CHECK (joined_at IS NULL OR
               (length(joined_at) = 10 AND joined_at GLOB '????-??-??')),
    left_at TEXT
        CHECK (left_at IS NULL OR
               (length(left_at) = 10 AND left_at GLOB '????-??-??')),
    CHECK (joined_at IS NULL OR left_at IS NULL OR left_at >= joined_at),
    FOREIGN KEY (ensemble_id) REFERENCES ensembles(ensemble_id) ON DELETE RESTRICT,
    FOREIGN KEY (musician_id) REFERENCES musicians(musician_id) ON DELETE RESTRICT
);

CREATE INDEX idx_ensemble_members_musician
    ON ensemble_members(musician_id);

-- Запрещает пересекающиеся периоды участия одного музыканта в одном ансамбле.
-- NULL в joined_at трактуется как очень ранняя дата, NULL в left_at — как открытый период.
CREATE TRIGGER trg_ensemble_members_no_overlap_insert
BEFORE INSERT ON ensemble_members
WHEN EXISTS (
    SELECT 1
    FROM ensemble_members em
    WHERE em.ensemble_id = NEW.ensemble_id
      AND em.musician_id = NEW.musician_id
      AND COALESCE(NEW.joined_at, '0001-01-01')
          <= COALESCE(em.left_at, '9999-12-31')
      AND COALESCE(em.joined_at, '0001-01-01')
          <= COALESCE(NEW.left_at, '9999-12-31')
)
BEGIN
    SELECT RAISE(ABORT, 'Пересекаются периоды участия музыканта в ансамбле');
END;

CREATE TRIGGER trg_ensemble_members_no_overlap_update
BEFORE UPDATE OF ensemble_id, musician_id, joined_at, left_at
ON ensemble_members
WHEN EXISTS (
    SELECT 1
    FROM ensemble_members em
    WHERE em.ensemble_id = NEW.ensemble_id
      AND em.musician_id = NEW.musician_id
      AND em.ensemble_member_id <> OLD.ensemble_member_id
      AND COALESCE(NEW.joined_at, '0001-01-01')
          <= COALESCE(em.left_at, '9999-12-31')
      AND COALESCE(em.joined_at, '0001-01-01')
          <= COALESCE(NEW.left_at, '9999-12-31')
)
BEGIN
    SELECT RAISE(ABORT, 'Пересекаются периоды участия музыканта в ансамбле');
END;

CREATE TABLE compositions (
    composition_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL
        CHECK (length(trim(title)) BETWEEN 1 AND 250),
    creation_year INTEGER
        CHECK (creation_year IS NULL OR creation_year BETWEEN 1000 AND 2100),
    description TEXT
);

CREATE TABLE composition_credits (
    composition_id INTEGER NOT NULL,
    musician_id INTEGER NOT NULL,
    credit_role TEXT NOT NULL
        CHECK (length(trim(credit_role)) BETWEEN 1 AND 100),
    PRIMARY KEY (composition_id, musician_id, credit_role),
    FOREIGN KEY (composition_id) REFERENCES compositions(composition_id) ON DELETE RESTRICT,
    FOREIGN KEY (musician_id) REFERENCES musicians(musician_id) ON DELETE RESTRICT
);

CREATE INDEX idx_composition_credits_musician
    ON composition_credits(musician_id);

CREATE TABLE performances (
    performance_id INTEGER PRIMARY KEY,
    composition_id INTEGER NOT NULL,
    ensemble_id INTEGER,
    conductor_id INTEGER,
    recorded_at TEXT
        CHECK (recorded_at IS NULL OR
               (length(recorded_at) = 10 AND recorded_at GLOB '????-??-??')),
    recording_location TEXT
        CHECK (recording_location IS NULL OR length(recording_location) <= 200),
    notes TEXT,
    FOREIGN KEY (composition_id) REFERENCES compositions(composition_id) ON DELETE RESTRICT,
    FOREIGN KEY (ensemble_id) REFERENCES ensembles(ensemble_id) ON DELETE RESTRICT,
    FOREIGN KEY (conductor_id) REFERENCES musicians(musician_id) ON DELETE RESTRICT
);

CREATE INDEX idx_performances_ensemble ON performances(ensemble_id);
CREATE INDEX idx_performances_composition ON performances(composition_id);

CREATE TABLE performance_musicians (
    performance_id INTEGER NOT NULL,
    musician_id INTEGER NOT NULL,
    participation_role TEXT NOT NULL
        CHECK (length(trim(participation_role)) BETWEEN 1 AND 100),
    PRIMARY KEY (performance_id, musician_id, participation_role),
    FOREIGN KEY (performance_id) REFERENCES performances(performance_id) ON DELETE CASCADE,
    FOREIGN KEY (musician_id) REFERENCES musicians(musician_id) ON DELETE RESTRICT
);

CREATE INDEX idx_performance_musicians_musician
    ON performance_musicians(musician_id);

-- ============================================================
-- 3. КАТАЛОГ ИЗДАНИЙ, ПРОИЗВОДИТЕЛИ И ПОСТАВЩИКИ
-- ============================================================

CREATE TABLE media_types (
    media_type_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
        CHECK (length(trim(name)) BETWEEN 1 AND 50),
    description TEXT
);

CREATE TABLE companies (
    company_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
        CHECK (length(trim(name)) BETWEEN 1 AND 200),
    country TEXT
        CHECK (country IS NULL OR length(country) <= 100),
    address TEXT,
    phone TEXT
        CHECK (phone IS NULL OR length(phone) <= 30),
    website TEXT
        CHECK (website IS NULL OR length(website) <= 255)
);

CREATE TABLE manufacturers (
    company_id INTEGER PRIMARY KEY,
    FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE RESTRICT
);

CREATE TABLE suppliers (
    company_id INTEGER PRIMARY KEY,
    FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE RESTRICT
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    catalog_number TEXT NOT NULL
        CHECK (length(trim(catalog_number)) BETWEEN 1 AND 100),
    title TEXT NOT NULL
        CHECK (length(trim(title)) BETWEEN 1 AND 250),
    media_type_id INTEGER NOT NULL,
    manufacturer_company_id INTEGER NOT NULL,
    release_date TEXT
        CHECK (release_date IS NULL OR
               (length(release_date) = 10 AND release_date GLOB '????-??-??')),
    description TEXT,
    cover_image TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    UNIQUE (manufacturer_company_id, catalog_number),
    FOREIGN KEY (media_type_id) REFERENCES media_types(media_type_id) ON DELETE RESTRICT,
    FOREIGN KEY (manufacturer_company_id) REFERENCES manufacturers(company_id) ON DELETE RESTRICT
);

CREATE INDEX idx_products_title ON products(title);
CREATE INDEX idx_products_media_type ON products(media_type_id);
CREATE INDEX idx_products_active ON products(is_active);

CREATE TABLE product_performances (
    product_performance_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    performance_id INTEGER NOT NULL,
    disc_number INTEGER NOT NULL DEFAULT 1 CHECK (disc_number > 0),
    track_number INTEGER NOT NULL CHECK (track_number > 0),
    track_title TEXT
        CHECK (track_title IS NULL OR length(track_title) <= 250),
    duration_seconds INTEGER
        CHECK (duration_seconds IS NULL OR duration_seconds > 0),
    UNIQUE (product_id, disc_number, track_number),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT,
    FOREIGN KEY (performance_id) REFERENCES performances(performance_id) ON DELETE RESTRICT
);

CREATE INDEX idx_product_performances_performance
    ON product_performances(performance_id);

CREATE TABLE product_suppliers (
    product_id INTEGER NOT NULL,
    supplier_company_id INTEGER NOT NULL,
    supplier_catalog_number TEXT
        CHECK (supplier_catalog_number IS NULL OR length(supplier_catalog_number) <= 100),
    is_preferred INTEGER NOT NULL DEFAULT 0
        CHECK (is_preferred IN (0, 1)),
    PRIMARY KEY (product_id, supplier_company_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT,
    FOREIGN KEY (supplier_company_id) REFERENCES suppliers(company_id) ON DELETE RESTRICT
);

CREATE INDEX idx_product_suppliers_supplier
    ON product_suppliers(supplier_company_id);

CREATE UNIQUE INDEX idx_product_one_preferred_supplier
    ON product_suppliers(product_id)
    WHERE is_preferred = 1;

-- ============================================================
-- 4. ИСТОРИЯ РОЗНИЧНЫХ И ЗАКУПОЧНЫХ ЦЕН
-- ============================================================

CREATE TABLE product_prices (
    price_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    retail_price INTEGER NOT NULL CHECK (retail_price >= 0),
    valid_from TEXT NOT NULL
        CHECK (length(valid_from) = 10 AND valid_from GLOB '????-??-??'),
    valid_to TEXT
        CHECK (valid_to IS NULL OR
               (length(valid_to) = 10 AND valid_to GLOB '????-??-??')),
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT
);

CREATE INDEX idx_product_prices_product_period
    ON product_prices(product_id, valid_from, valid_to);

CREATE TRIGGER trg_product_prices_no_overlap_insert
BEFORE INSERT ON product_prices
WHEN EXISTS (
    SELECT 1 FROM product_prices p
    WHERE p.product_id = NEW.product_id
      AND NEW.valid_from <= COALESCE(p.valid_to, '9999-12-31')
      AND p.valid_from <= COALESCE(NEW.valid_to, '9999-12-31')
)
BEGIN
    SELECT RAISE(ABORT, 'Пересекаются периоды действия розничных цен');
END;

CREATE TRIGGER trg_product_prices_no_overlap_update
BEFORE UPDATE OF product_id, valid_from, valid_to ON product_prices
WHEN EXISTS (
    SELECT 1 FROM product_prices p
    WHERE p.product_id = NEW.product_id
      AND p.price_id <> OLD.price_id
      AND NEW.valid_from <= COALESCE(p.valid_to, '9999-12-31')
      AND p.valid_from <= COALESCE(NEW.valid_to, '9999-12-31')
)
BEGIN
    SELECT RAISE(ABORT, 'Пересекаются периоды действия розничных цен');
END;

CREATE TABLE supplier_product_prices (
    supplier_price_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    supplier_company_id INTEGER NOT NULL,
    wholesale_price INTEGER NOT NULL CHECK (wholesale_price >= 0),
    valid_from TEXT NOT NULL
        CHECK (length(valid_from) = 10 AND valid_from GLOB '????-??-??'),
    valid_to TEXT
        CHECK (valid_to IS NULL OR
               (length(valid_to) = 10 AND valid_to GLOB '????-??-??')),
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    FOREIGN KEY (product_id, supplier_company_id)
        REFERENCES product_suppliers(product_id, supplier_company_id) ON DELETE RESTRICT
);

CREATE INDEX idx_supplier_prices_product_period
    ON supplier_product_prices(product_id, supplier_company_id, valid_from, valid_to);

CREATE TRIGGER trg_supplier_prices_no_overlap_insert
BEFORE INSERT ON supplier_product_prices
WHEN EXISTS (
    SELECT 1 FROM supplier_product_prices p
    WHERE p.product_id = NEW.product_id
      AND p.supplier_company_id = NEW.supplier_company_id
      AND NEW.valid_from <= COALESCE(p.valid_to, '9999-12-31')
      AND p.valid_from <= COALESCE(NEW.valid_to, '9999-12-31')
)
BEGIN
    SELECT RAISE(ABORT, 'Пересекаются периоды действия закупочных цен');
END;

CREATE TRIGGER trg_supplier_prices_no_overlap_update
BEFORE UPDATE OF product_id, supplier_company_id, valid_from, valid_to
ON supplier_product_prices
WHEN EXISTS (
    SELECT 1 FROM supplier_product_prices p
    WHERE p.product_id = NEW.product_id
      AND p.supplier_company_id = NEW.supplier_company_id
      AND p.supplier_price_id <> OLD.supplier_price_id
      AND NEW.valid_from <= COALESCE(p.valid_to, '9999-12-31')
      AND p.valid_from <= COALESCE(NEW.valid_to, '9999-12-31')
)
BEGIN
    SELECT RAISE(ABORT, 'Пересекаются периоды действия закупочных цен');
END;

-- ============================================================
-- 5. ЗАКАЗЫ, ПОЗИЦИИ ЗАКАЗОВ И СКЛАДСКИЕ ДВИЖЕНИЯ
-- ============================================================

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    customer_name TEXT NOT NULL
        CHECK (length(trim(customer_name)) BETWEEN 1 AND 200),
    customer_phone TEXT NOT NULL
        CHECK (length(trim(customer_phone)) BETWEEN 1 AND 30),
    customer_email TEXT
        CHECK (customer_email IS NULL OR length(trim(customer_email)) <= 254),
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'processing', 'completed', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    comment TEXT,
    CHECK (
        (status = 'completed' AND completed_at IS NOT NULL)
        OR (status <> 'completed' AND completed_at IS NULL)
    ),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT
);

CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_orders_status_created ON orders(status, created_at);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
    product_title_snapshot TEXT NOT NULL
        CHECK (length(trim(product_title_snapshot)) BETWEEN 1 AND 250),
    catalog_number_snapshot TEXT NOT NULL
        CHECK (length(trim(catalog_number_snapshot)) BETWEEN 1 AND 100),
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE RESTRICT,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT
);

CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);

CREATE TABLE inventory_movements (
    movement_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    movement_type TEXT NOT NULL
        CHECK (movement_type IN
               ('receipt', 'sale', 'return', 'writeoff', 'adjustment_in', 'adjustment_out')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost INTEGER NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    order_item_id INTEGER,
    comment TEXT,
    CHECK (movement_type <> 'sale' OR order_item_id IS NOT NULL),
    CHECK (movement_type <> 'return' OR order_item_id IS NOT NULL),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT,
    FOREIGN KEY (order_item_id) REFERENCES order_items(order_item_id) ON DELETE RESTRICT
);

CREATE INDEX idx_inventory_product_created
    ON inventory_movements(product_id, created_at);
CREATE INDEX idx_inventory_order_item
    ON inventory_movements(order_item_id);

CREATE UNIQUE INDEX idx_inventory_one_sale_per_order_item
    ON inventory_movements(order_item_id)
    WHERE movement_type = 'sale';

-- Остаток = поступления + возвраты + корректировки вверх
-- минус продажи + списания + корректировки вниз.
CREATE TRIGGER trg_inventory_prevent_negative_stock
BEFORE INSERT ON inventory_movements
WHEN NEW.movement_type IN ('sale', 'writeoff', 'adjustment_out')
 AND (
    COALESCE((
        SELECT SUM(
            CASE
                WHEN movement_type IN ('receipt', 'return', 'adjustment_in') THEN quantity
                WHEN movement_type IN ('sale', 'writeoff', 'adjustment_out') THEN -quantity
                ELSE 0
            END
        )
        FROM inventory_movements
        WHERE product_id = NEW.product_id
    ), 0) < NEW.quantity
 )
BEGIN
    SELECT RAISE(ABORT, 'Недостаточно товара на складе');
END;

-- Продажа должна относиться к позиции завершённого заказа;
-- товар и количество движения должны совпадать с позицией заказа.
CREATE TRIGGER trg_inventory_validate_sale
BEFORE INSERT ON inventory_movements
WHEN NEW.movement_type = 'sale'
 AND NOT EXISTS (
    SELECT 1
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    WHERE oi.order_item_id = NEW.order_item_id
      AND oi.product_id = NEW.product_id
      AND oi.quantity = NEW.quantity
      AND o.status = 'completed'
      AND o.completed_at IS NOT NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'Продажа должна соответствовать позиции завершённого заказа');
END;

-- Возврат связывается с исходной позицией заказа, по которой ранее была продажа.
CREATE TRIGGER trg_inventory_validate_return
BEFORE INSERT ON inventory_movements
WHEN NEW.movement_type = 'return'
 AND NOT EXISTS (
    SELECT 1
    FROM order_items oi
    JOIN inventory_movements sale
      ON sale.order_item_id = oi.order_item_id
     AND sale.movement_type = 'sale'
    WHERE oi.order_item_id = NEW.order_item_id
      AND oi.product_id = NEW.product_id
      AND COALESCE((
          SELECT SUM(r.quantity)
          FROM inventory_movements r
          WHERE r.order_item_id = oi.order_item_id
            AND r.movement_type = 'return'
      ), 0) + NEW.quantity <= sale.quantity
 )
BEGIN
    SELECT RAISE(ABORT, 'Возврат должен соответствовать ранее проданной позиции заказа и не превышать её количество');
END;

-- Журнал складских движений неизменяем: исправления выполняются новыми движениями.
CREATE TRIGGER trg_inventory_no_update
BEFORE UPDATE ON inventory_movements
BEGIN
    SELECT RAISE(ABORT, 'Изменение складских движений запрещено; добавьте корректирующее движение');
END;

CREATE TRIGGER trg_inventory_no_delete
BEFORE DELETE ON inventory_movements
BEGIN
    SELECT RAISE(ABORT, 'Удаление складских движений запрещено');
END;

-- ============================================================
-- 6. СПИСКИ ЖЕЛАЕМОГО
-- ============================================================

CREATE TABLE wishlists (
    wishlist_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE wishlist_items (
    wishlist_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (wishlist_id, product_id),
    FOREIGN KEY (wishlist_id) REFERENCES wishlists(wishlist_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT
);

CREATE INDEX idx_wishlist_items_product
    ON wishlist_items(product_id);

-- ============================================================
-- 7. ПРЕДСТАВЛЕНИЯ ДЛЯ РАСЧЁТНЫХ ПОКАЗАТЕЛЕЙ
-- ============================================================

-- Текущий остаток каждого издания. Нулевой остаток также отображается.
CREATE VIEW v_product_stock AS
SELECT
    p.product_id,
    p.catalog_number,
    p.title,
    COALESCE(SUM(
        CASE
            WHEN im.movement_type IN ('receipt', 'return', 'adjustment_in')
                THEN im.quantity
            WHEN im.movement_type IN ('sale', 'writeoff', 'adjustment_out')
                THEN -im.quantity
            ELSE 0
        END
    ), 0) AS stock,
    COALESCE(SUM(
        CASE
            WHEN im.movement_type IN ('receipt', 'return', 'adjustment_in') THEN im.quantity
            WHEN im.movement_type IN ('sale', 'writeoff', 'adjustment_out') THEN -im.quantity
            ELSE 0
        END
    ), 0) AS stock_quantity
FROM products p
LEFT JOIN inventory_movements im ON im.product_id = p.product_id
GROUP BY p.product_id, p.catalog_number, p.title;

-- Продажи по годам рассчитываются по завершённым заказам.
-- Возвраты учитываются отдельно и вычитаются из количества проданного товара.
CREATE VIEW v_product_sales_by_year AS
SELECT
    oi.product_id,
    p.title AS product_title,
    CAST(strftime('%Y', o.completed_at) AS INTEGER) AS sales_year,
    SUM(CASE WHEN im.movement_type = 'sale' THEN im.quantity ELSE 0 END)
      - SUM(CASE WHEN im.movement_type = 'return' THEN im.quantity ELSE 0 END)
      AS quantity_sold,
    SUM(CASE WHEN im.movement_type = 'sale' THEN im.quantity ELSE 0 END)
      - SUM(CASE WHEN im.movement_type = 'return' THEN im.quantity ELSE 0 END)
      AS net_quantity
FROM order_items oi
JOIN products p ON p.product_id = oi.product_id
JOIN orders o ON o.order_id = oi.order_id
JOIN inventory_movements im ON im.order_item_id = oi.order_item_id
WHERE o.status = 'completed'
  AND im.movement_type IN ('sale', 'return')
GROUP BY oi.product_id, p.title, CAST(strftime('%Y', o.completed_at) AS INTEGER);

-- ============================================================
-- 8. НАЧАЛЬНЫЕ СПРАВОЧНЫЕ ДАННЫЕ
-- ============================================================

INSERT INTO roles (role_name, description)
VALUES
    ('customer', 'Зарегистрированный покупатель'),
    ('employee', 'Сотрудник музыкального магазина');

INSERT INTO media_types (name, description)
VALUES
    ('CD', 'Компакт-диск'),
    ('DVD', 'Цифровой видеодиск'),
    ('Винил', 'Виниловая грампластинка'),
    ('Кассета', 'Аудиокассета');

COMMIT;

-- ============================================================
-- КОНЕЦ СХЕМЫ
-- ============================================================
