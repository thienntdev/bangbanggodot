-- ============================================================================
-- BANGBANG GAME SERVER - DATABASE SCHEMA (PostgreSQL)
-- Architecture: Users -> Characters (1 Account có nhiều Nhân vật)
-- Hybrid Design: Dedicated Columns (tra cứu/update nhanh) + JSONB (linh hoạt)
-- ============================================================================

-- 1. BẢNG TÀI KHOẢN NGƯỜI DÙNG (USERS / ACCOUNTS)
-- Quản lý tài khoản đăng nhập (username, mật khẩu, trạng thái tài khoản)
CREATE TABLE IF NOT EXISTS users (
    user_id BIGSERIAL PRIMARY KEY,                  -- ID tài khoản duy nhất (10001, 10002...)
    username VARCHAR(64) UNIQUE NOT NULL,           -- Tên đăng nhập
    pass_hash BYTEA NOT NULL,                       -- Mật khẩu Bcrypt
    status SMALLINT NOT NULL DEFAULT 0,             -- 0: Hoạt động, 1: Bị khóa
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- 2. BẢNG NHÂN VẬT IN-GAME (CHARACTERS / PLAYERS)
-- 1 User có thể sở hữu nhiều Character (Hiện tại tạo 1 char mặc định, client hỗ trợ chọn/tạo nhiều char)
CREATE TABLE IF NOT EXISTS characters (
    char_id BIGSERIAL PRIMARY KEY,                  -- ID nhân vật trong game (Oid)
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    char_uuid VARCHAR(64) UNIQUE NOT NULL,          -- UUID nhân vật
    name VARCHAR(64) NOT NULL,                      -- Tên hiển thị nhân vật
    level SMALLINT NOT NULL DEFAULT 1,              -- Cấp độ nhân vật
    exp INT NOT NULL DEFAULT 0,                     -- Điểm kinh nghiệm (EXP)
    cash INT NOT NULL DEFAULT 10000,                -- Xu nạp
    golden INT NOT NULL DEFAULT 5000,               -- Xu khoá
    silver INT NOT NULL DEFAULT 50000,              -- Bạc ingame
    thew INT NOT NULL DEFAULT 200,                  -- Thể lực (Energy)
    avatar_id INT NOT NULL DEFAULT 0,               -- Avatar ID
    vip_level SMALLINT NOT NULL DEFAULT 0,          -- Cấp VIP
    elo INT NOT NULL DEFAULT 1000,                  -- Điểm ELO xếp hạng
    data JSONB NOT NULL DEFAULT '{}'::jsonb,        -- Dữ liệu mở rộng (quân hàm, danh hiệu, tinh thể...)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_characters_user_id ON characters(user_id);
CREATE INDEX IF NOT EXISTS idx_characters_char_uuid ON characters(char_uuid);

-- 3. BẢNG TANK CỦA NHÂN VẬT (CHARACTER TANKS)
-- Lưu danh sách xe tank sở hữu, cấp độ (1-6), cường hóa, skin, cờ chủ chiến
CREATE TABLE IF NOT EXISTS character_tanks (
    tank_uuid VARCHAR(64) PRIMARY KEY,              -- UUID của tank instance
    char_id BIGINT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
    tank_id INT NOT NULL,                           -- ID loại tank (103, 104, 105, 106, 107...)
    tank_level SMALLINT NOT NULL DEFAULT 1,         -- Cấp độ tank (Level 1 -> 6)
    tank_exp INT NOT NULL DEFAULT 0,                -- EXP hiện tại của tank
    stth_level SMALLINT NOT NULL DEFAULT 0,         -- Cấp cường hóa (Strengthen Level)
    stth_count SMALLINT NOT NULL DEFAULT 0,         -- Số lần đã cường hóa
    ext_flag INT NOT NULL DEFAULT 0,                -- Cờ trạng thái (bit 2 = JOIN_BATTLE: Chủ chiến)
    external_id INT NOT NULL DEFAULT 0,             -- ID skin ngoại trang
    halo_id INT NOT NULL DEFAULT 0,                 -- ID vòng sáng halo
    war_count INT NOT NULL DEFAULT 0,               -- Số trận chiến
    week_war_count INT NOT NULL DEFAULT 0,          -- Số trận trong tuần
    cont_type SMALLINT NOT NULL DEFAULT 0,          -- 0: Vĩnh viễn (OWN), 1: Thuê (HIRE)
    exist_time INT NOT NULL DEFAULT 0,              -- Thời gian hết hạn thuê (0 = vĩnh viễn)
    proficiency_val INT NOT NULL DEFAULT 0,         -- Độ thông thạo của tank
    battle_gains INT NOT NULL DEFAULT 0,            -- Chiến tích đạt được
    tal_page_uuid VARCHAR(64) NOT NULL DEFAULT '',  -- UUID trang kỹ năng/kỹ thuật
    data JSONB NOT NULL DEFAULT '{}'::jsonb,        -- Mở rộng chỉ số phụ (nếu có)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_character_tanks_char_id ON character_tanks(char_id);

-- 4. BẢNG RƯƠNG ĐỒ / VẬT PHẨM (CHARACTER ITEMS & INVENTORY)
-- Lưu trữ vật phẩm theo từng ô (slot_no) và loại rương (cont_type: 2: VP, 3: Nguyên liệu, 4: Thời trang, 6: Skin, 7: Decor...)
CREATE TABLE IF NOT EXISTS character_items (
    item_uuid VARCHAR(64) PRIMARY KEY,              -- UUID vật phẩm instance
    char_id BIGINT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
    cont_type SMALLINT NOT NULL,                    -- 2: VP, 3: Nguyên liệu, 4, 6, 7...
    slot_no SMALLINT NOT NULL,                      -- Vị trí ô trong rương
    template_id INT NOT NULL,                       -- ID vật phẩm (template)
    count INT NOT NULL DEFAULT 1,                   -- Số lượng vật phẩm
    level SMALLINT NOT NULL DEFAULT 1,              -- Cấp độ
    up_level SMALLINT NOT NULL DEFAULT 0,           -- Cấp cường hóa
    exp INT NOT NULL DEFAULT 0,
    rank SMALLINT NOT NULL DEFAULT 1,               -- Phẩm chất: 1: Thường, 2: Tốt, 3: Hiếm, 4: Cực hiếm, 5: Truyền thuyết
    ext_flag INT NOT NULL DEFAULT 0,                -- Trạng thái khóa (1 = SYS_BIND)
    life_time INT NOT NULL DEFAULT 0,               -- Hạn sử dụng (0 = vĩnh viễn)
    create_time INT NOT NULL DEFAULT 0,             -- Timestamp tạo
    data JSONB NOT NULL DEFAULT '{}'::jsonb,        -- Thuộc tính mở rộng
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_char_item_slot UNIQUE (char_id, cont_type, slot_no)
);

CREATE INDEX IF NOT EXISTS idx_character_items_char_cont ON character_items(char_id, cont_type);

-- 5. BẢNG BANG HỘI (GUILDS)
CREATE TABLE IF NOT EXISTS guilds (
    guild_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,
    level SMALLINT NOT NULL DEFAULT 1,
    leader_char_id BIGINT NOT NULL REFERENCES characters(char_id),
    coin INT NOT NULL DEFAULT 0,                    -- Quỹ bang
    glory INT NOT NULL DEFAULT 0,                   -- Điểm vinh dự bang
    notice TEXT NOT NULL DEFAULT '',                -- Thông báo bang
    data JSONB NOT NULL DEFAULT '{}'::jsonb,        -- Kỹ năng bang, cấu hình bang
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. BẢNG THÀNH VIÊN BANG HỘI (GUILD MEMBERS)
CREATE TABLE IF NOT EXISTS guild_members (
    char_id BIGINT PRIMARY KEY REFERENCES characters(char_id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    role SMALLINT NOT NULL DEFAULT 0,               -- 1: Bang chủ, 2: Phó bang, 0: Thành viên
    merit INT NOT NULL DEFAULT 0,                   -- Điểm cống hiến
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_guild_members_guild_id ON guild_members(guild_id);

-- 7. BẢNG HÒM THƯ & QUÀ TIẾP TẾ (OFFLINE MAILS)
CREATE TABLE IF NOT EXISTS offline_mails (
    mail_id VARCHAR(64) PRIMARY KEY,
    recipient_char_id BIGINT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
    sender_name VARCHAR(64) NOT NULL DEFAULT 'Hệ Thống',
    subject VARCHAR(128) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    rewards JSONB NOT NULL DEFAULT '[]'::jsonb,     -- Danh sách quà tặng: [{"id": 4050011, "count": 10}]
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    is_claimed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_offline_mails_recipient ON offline_mails(recipient_char_id);

-- 8. BẢNG MÙA GIẢI XẾP HẠNG (RANK SEASONS)
CREATE TABLE IF NOT EXISTS rank_seasons (
    season_id SERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- 9. BẢNG ĐIỂM XẾP HẠNG (RANK ENTRIES)
CREATE TABLE IF NOT EXISTS rank_entries (
    char_id BIGINT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
    season_id INT NOT NULL REFERENCES rank_seasons(season_id) ON DELETE CASCADE,
    elo INT NOT NULL DEFAULT 1000,
    played INT NOT NULL DEFAULT 0,
    wins INT NOT NULL DEFAULT 0,
    losses INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (char_id, season_id)
);

-- 10. BẢNG LỊCH SỬ TRẬN ĐẤU (MATCH HISTORY)
CREATE TABLE IF NOT EXISTS match_history (
    match_uuid VARCHAR(64) PRIMARY KEY,
    room_id INT NOT NULL,
    map_id INT NOT NULL,
    mode SMALLINT NOT NULL DEFAULT 1,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 11. BẢNG BOSS THẾ GIỚI (WORLD BOSS)
CREATE TABLE IF NOT EXISTS world_boss_rounds (
    round_id SERIAL PRIMARY KEY,
    boss_id INT NOT NULL,
    max_hp BIGINT NOT NULL,
    current_hp BIGINT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS world_boss_scores (
    round_id INT NOT NULL REFERENCES world_boss_rounds(round_id) ON DELETE CASCADE,
    char_id BIGINT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
    damage BIGINT NOT NULL DEFAULT 0,
    attained_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (round_id, char_id)
);

-- ============================================================================
-- AUTO MIGRATION TỪ BẢNG CŨ (NẾU CÓ DỮ LIỆU CŨ TỪ BẢNG PLAYERS)
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'players') THEN
        INSERT INTO users (user_id, username, pass_hash, created_at, updated_at)
        SELECT acct_id, username, pass_hash, created_at, updated_at FROM players
        ON CONFLICT (username) DO NOTHING;

        INSERT INTO characters (char_id, user_id, char_uuid, name, level, exp, cash, golden, silver, created_at, updated_at)
        SELECT acct_id, acct_id, char_uuid, name, level, exp, cash, golden, silver, created_at, updated_at FROM players
        ON CONFLICT (char_id) DO NOTHING;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'player_tanks') THEN
        INSERT INTO character_tanks (
            tank_uuid, char_id, tank_id, tank_level, tank_exp, stth_level, stth_count,
            ext_flag, external_id, halo_id, war_count, week_war_count, cont_type, exist_time,
            proficiency_val, battle_gains, tal_page_uuid, created_at, updated_at
        )
        SELECT 
            tank_uuid, acct_id, tank_id, tank_level, tank_exp, stth_level, stth_count,
            ext_flag, external_id, halo_id, war_count, week_war_count, cont_type, exist_time,
            proficiency_val, battle_gains, tal_page_uuid, created_at, updated_at
        FROM player_tanks
        ON CONFLICT (tank_uuid) DO NOTHING;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'player_items') THEN
        INSERT INTO character_items (
            item_uuid, char_id, cont_type, slot_no, template_id, count, level, up_level,
            exp, rank, ext_flag, life_time, create_time, created_at, updated_at
        )
        SELECT 
            item_uuid, acct_id, cont_type, slot_no, template_id, count, level, up_level,
            exp, rank, ext_flag, life_time, create_time, created_at, updated_at
        FROM player_items
        ON CONFLICT (item_uuid) DO NOTHING;
    END IF;
END $$;

-- =============================================================
-- 13. DỮ LIỆU KHỞI TẠO MẪU CHO CÁC BẢNG RUNTIME (SEED DATA)
-- =============================================================

-- Mùa giải xếp hạng (Rank Seasons)
INSERT INTO rank_seasons (season_id, name, starts_at, ends_at, is_active) 
VALUES 
    (1, 'Mùa Giải 1', '2026-10-27 17:00:00+00', '2026-11-10 17:00:00+00', FALSE),
    (2, 'Mùa Giải 2', '2026-11-10 17:00:00+00', '2026-11-24 17:00:00+00', TRUE)
ON CONFLICT (season_id) DO NOTHING;

-- Boss thế giới (World Boss Rounds)
INSERT INTO world_boss_rounds (round_id, boss_id, max_hp, current_hp, is_active, starts_at, ends_at)
VALUES 
    (1, 10000001, 10000000000, 9619773298, TRUE, '2026-11-16 05:45:43+00', '2026-11-16 06:15:43+00'),
    (2, 10000001, 10000000000, 10000000000, FALSE, '2026-11-16 16:40:45+00', '2026-11-16 17:10:45+00'),
    (3, 10000001, 10000000000, 10000000000, FALSE, '2026-11-16 16:52:05+00', '2026-11-16 17:22:05+00')
ON CONFLICT (round_id) DO NOTHING;

-- Thư tiếp tế mẫu (Offline Mails)
INSERT INTO offline_mails (mail_id, recipient_char_id, sender_name, subject, content, rewards, is_read, is_claimed)
SELECT 
    'mail-d8957abddc764bcfa312fe360ae22af6', char_id, 'Hệ Thống', 'Quà tiếp tế Bang Bang', 
    'Chúc mừng chỉ huy tham gia BangBang! Đây là quà tiếp tế tân thủ dành riêng cho bạn.', 
    '[{"category":"helper","container":5,"id":4431007,"key":"item:4431007","kind":"item","level":1,"max_quantity":135,"name":"Hỏa Kỳ Lân","quantity":1,"stack_max":1,"unique":false},{"category":"helper","container":5,"id":4441005,"key":"item:4441005","kind":"item","level":1,"max_quantity":135,"name":"Bé Hỏa Kỳ Lân","quantity":1,"stack_max":1,"unique":false}]'::jsonb, 
    FALSE, FALSE
FROM characters
LIMIT 1
ON CONFLICT (mail_id) DO NOTHING;

-- Bang hội mẫu (Guilds)
INSERT INTO guilds (guild_id, name, level, leader_char_id, coin, glory, notice, data)
SELECT 2, 'chan de', 1, char_id, 1300, 500, 'Chào mừng đến với bang hội!', '{"level":1,"coin":1300,"leader":30000792,"vice":0,"created":1793019281,"settings":0,"min_level":1,"min_ladder":0,"notice":"","recruit":"","channel":"","research":{"1100":9,"1200":9,"1300":9,"1400":9,"1500":9,"1600":9,"1700":9,"1800":9,"1900":9,"2000":9,"2100":9,"2200":9,"2300":9,"2400":9,"2500":5,"2600":9,"2700":9,"2750":9,"2800":5,"2900":9,"3000":9,"3100":9,"3200":9,"3300":9}}'::jsonb
FROM characters
LIMIT 1
ON CONFLICT (guild_id) DO NOTHING;

INSERT INTO guilds (guild_id, name, level, leader_char_id, coin, glory, notice, data)
SELECT 3, '1212', 2, char_id, 300, 500, 'chan map', '{"level": 2, "coin": 300, "leader": 30000794, "vice": 0, "created": 1794809182, "settings": 0, "min_level": 1, "min_ladder": 0, "notice": "chan map", "recruit": "vo các e êi", "channel": "", "research": {"1100": 2, "1200": 1, "1400": 1, "1300": 1, "1500": 1, "1800": 1, "1900": 1}}'::jsonb
FROM characters
LIMIT 1
ON CONFLICT (guild_id) DO NOTHING;
