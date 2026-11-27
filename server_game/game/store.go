package game

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"fmt"
	"log"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	_ "github.com/lib/pq"
	"golang.org/x/crypto/bcrypt"
)

// User represents a login account.
type User struct {
	UserID   uint32
	Username string
	PassHash []byte // bcrypt hash
	Status   uint8  // 0: active, 1: banned
	Created  time.Time
}

// Character represents an in-game character profile (1 User can have multiple Characters).
type Character struct {
	CharID         uint32 // Acts as AcctID / ProfileID in Sixcube protocol
	UserID         uint32
	CharUuid       string
	Name           string
	Level          uint8
	Exp            int32
	Cash           int32 // xu
	Golden         int32 // xu khoá
	Silver         int32 // bạc
	Thew           int32 // thể lực
	AvatarID       uint32
	VipLevel       uint8
	Elo            int32
	Tanks          []PlayerTank
	Items          []PlayerItem
	Created        time.Time
}

// PlayerTank represents a tank instance owned by a character.
type PlayerTank struct {
	TankUuid        string
	TankID          uint32
	TankLevel       uint8
	TankExp         uint32
	ExtFlag         uint32 // bit 2 = JOIN_BATTLE (chủ chiến)
	StthLevel       uint8  // Cấp cường hóa
	ExternalID      uint32 // Skin/ngoại trang
	WarCount        uint32
	WeekWarCount    uint32
	ContType        uint8
	CashHireCount   uint8
	CoinHireCount   uint8
	ExistTime       uint32
	HaloID          uint32
	SkinFrameType   uint8
	OwnTime         uint32
	StthCount       uint8
	ComSkillID      uint32
	CrystalSchemeID uint8
	TalPageUuid     string
	ProficiencyVal  uint32
	BattleGains     int32
}

// PlayerItem represents an item in a character's inventory/bag.
type PlayerItem struct {
	ItemUuid   string
	ContType   uint8  // 2: VP, 3: Nguyên liệu, 4: Thời trang, 6: Skin, 7: Trang trí...
	SlotNo     int16  // Vị trí ô trong rương
	TemplateID uint32 // ID vật phẩm
	Count      int32  // Số lượng
	Level      uint8
	UpLevel    uint8
	Exp        int32
	Rank       uint8
	UpCost     int32
	RankCost   int32
	LifeTime   uint32
	ExtFlag    uint32
	CreateTime uint32
}

// Session represents an active login session tied to a character.
type Session struct {
	SessionKey uint32
	UserID     uint32
	CharID     uint32
	Character  *Character
	ExpiresAt  time.Time
}

// Store holds memory-cached accounts, characters, and sessions with PostgreSQL persistence.
type Store struct {
	mu         sync.RWMutex
	users      map[string]*User       // username -> User
	characters map[uint32]*Character  // char_id -> Character
	userChars  map[uint32][]uint32    // user_id -> [char_id, ...]
	sessions   map[uint32]*Session    // session_key -> Session
	nextUserID atomic.Uint32
	nextCharID atomic.Uint32
	nextSess   atomic.Uint32
	db         *sql.DB
}

const autoMigrateSQL = `
-- 1. Users
CREATE TABLE IF NOT EXISTS users (
    user_id BIGSERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    pass_hash BYTEA NOT NULL,
    status SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- 2. Characters
CREATE TABLE IF NOT EXISTS characters (
    char_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    char_uuid VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(64) NOT NULL,
    level SMALLINT NOT NULL DEFAULT 1,
    exp INT NOT NULL DEFAULT 0,
    cash INT NOT NULL DEFAULT 10000,
    golden INT NOT NULL DEFAULT 5000,
    silver INT NOT NULL DEFAULT 50000,
    thew INT NOT NULL DEFAULT 200,
    avatar_id INT NOT NULL DEFAULT 0,
    vip_level SMALLINT NOT NULL DEFAULT 0,
    elo INT NOT NULL DEFAULT 1000,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_characters_user_id ON characters(user_id);
CREATE INDEX IF NOT EXISTS idx_characters_char_uuid ON characters(char_uuid);

-- 3. Character Tanks
CREATE TABLE IF NOT EXISTS character_tanks (
    tank_uuid VARCHAR(64) PRIMARY KEY,
    char_id BIGINT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
    tank_id INT NOT NULL,
    tank_level SMALLINT NOT NULL DEFAULT 1,
    tank_exp INT NOT NULL DEFAULT 0,
    stth_level SMALLINT NOT NULL DEFAULT 0,
    stth_count SMALLINT NOT NULL DEFAULT 0,
    ext_flag INT NOT NULL DEFAULT 0,
    external_id INT NOT NULL DEFAULT 0,
    halo_id INT NOT NULL DEFAULT 0,
    war_count INT NOT NULL DEFAULT 0,
    week_war_count INT NOT NULL DEFAULT 0,
    cont_type SMALLINT NOT NULL DEFAULT 0,
    exist_time INT NOT NULL DEFAULT 0,
    proficiency_val INT NOT NULL DEFAULT 0,
    battle_gains INT NOT NULL DEFAULT 0,
    tal_page_uuid VARCHAR(64) NOT NULL DEFAULT '',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_character_tanks_char_id ON character_tanks(char_id);

-- 4. Character Items (Inventory / Bags)
CREATE TABLE IF NOT EXISTS character_items (
    item_uuid VARCHAR(64) PRIMARY KEY,
    char_id BIGINT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
    cont_type SMALLINT NOT NULL,
    slot_no SMALLINT NOT NULL,
    template_id INT NOT NULL,
    count INT NOT NULL DEFAULT 1,
    level SMALLINT NOT NULL DEFAULT 1,
    up_level SMALLINT NOT NULL DEFAULT 0,
    exp INT NOT NULL DEFAULT 0,
    rank SMALLINT NOT NULL DEFAULT 1,
    ext_flag INT NOT NULL DEFAULT 0,
    life_time INT NOT NULL DEFAULT 0,
    create_time INT NOT NULL DEFAULT 0,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_char_item_slot UNIQUE (char_id, cont_type, slot_no)
);

CREATE INDEX IF NOT EXISTS idx_character_items_char_cont ON character_items(char_id, cont_type);

-- 5. Guilds
CREATE TABLE IF NOT EXISTS guilds (
    guild_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,
    level SMALLINT NOT NULL DEFAULT 1,
    leader_char_id BIGINT NOT NULL REFERENCES characters(char_id),
    coin INT NOT NULL DEFAULT 0,
    glory INT NOT NULL DEFAULT 0,
    notice TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Guild Members
CREATE TABLE IF NOT EXISTS guild_members (
    char_id BIGINT PRIMARY KEY REFERENCES characters(char_id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    role SMALLINT NOT NULL DEFAULT 0,
    merit INT NOT NULL DEFAULT 0,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_guild_members_guild_id ON guild_members(guild_id);

-- 7. Offline Mails
CREATE TABLE IF NOT EXISTS offline_mails (
    mail_id VARCHAR(64) PRIMARY KEY,
    recipient_char_id BIGINT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
    sender_name VARCHAR(64) NOT NULL DEFAULT 'Hệ Thống',
    subject VARCHAR(128) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    rewards JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    is_claimed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_offline_mails_recipient ON offline_mails(recipient_char_id);

-- 8. Rank Seasons & Entries
CREATE TABLE IF NOT EXISTS rank_seasons (
    season_id SERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

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

-- 9. Match History
CREATE TABLE IF NOT EXISTS match_history (
    match_uuid VARCHAR(64) PRIMARY KEY,
    room_id INT NOT NULL,
    map_id INT NOT NULL,
    mode SMALLINT NOT NULL DEFAULT 1,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 10. World Boss
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

-- 11. Data Migration from legacy players table (if exists)
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
`

// NewStore creates a new in-memory only Store.
func NewStore() *Store {
	s := &Store{
		users:      make(map[string]*User),
		characters: make(map[uint32]*Character),
		userChars:  make(map[uint32][]uint32),
		sessions:   make(map[uint32]*Session),
	}
	s.nextUserID.Store(10001)
	s.nextCharID.Store(10001)
	s.nextSess.Store(1)
	return s
}

// NewStoreWithDB creates a Store backed by PostgreSQL.
func NewStoreWithDB(databaseURL string) (*Store, error) {
	connStr := strings.TrimSpace(databaseURL)
	if !strings.Contains(connStr, "sslmode=") {
		if strings.Contains(connStr, "?") {
			connStr += "&sslmode=require"
		} else {
			connStr += "?sslmode=require"
		}
	}

	db, err := sql.Open("postgres", connStr)
	if err != nil {
		return nil, fmt.Errorf("open postgres connection: %w", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := db.PingContext(ctx); err != nil {
		db.Close()
		return nil, fmt.Errorf("ping postgres: %w", err)
	}

	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(30 * time.Minute)

	s := &Store{
		users:      make(map[string]*User),
		characters: make(map[uint32]*Character),
		userChars:  make(map[uint32][]uint32),
		sessions:   make(map[uint32]*Session),
		db:         db,
	}
	s.nextUserID.Store(10001)
	s.nextCharID.Store(10001)
	s.nextSess.Store(1)

	if err := s.autoMigrate(); err != nil {
		db.Close()
		return nil, fmt.Errorf("auto-migrate schema: %w", err)
	}

	if err := s.loadAllDataFromDB(); err != nil {
		db.Close()
		return nil, fmt.Errorf("load database: %w", err)
	}

	return s, nil
}

func (s *Store) autoMigrate() error {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	_, err := s.db.ExecContext(ctx, autoMigrateSQL)
	if err != nil {
		return err
	}
	log.Println("[db] ✅ PostgreSQL comprehensive schema (users, characters, tanks, items, guilds, mails, ranks) migrated successfully.")
	return nil
}

func (s *Store) loadAllDataFromDB() error {
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()

	s.mu.Lock()
	defer s.mu.Unlock()

	// 1. Load users
	userRows, err := s.db.QueryContext(ctx, "SELECT user_id, username, pass_hash, status, created_at FROM users")
	if err != nil {
		return fmt.Errorf("query users: %w", err)
	}
	defer userRows.Close()

	var maxUserID uint32 = 10000
	for userRows.Next() {
		var uid int64
		var st int16
		u := &User{}
		if err := userRows.Scan(&uid, &u.Username, &u.PassHash, &st, &u.Created); err != nil {
			return fmt.Errorf("scan user: %w", err)
		}
		u.UserID = uint32(uid)
		u.Status = uint8(st)
		if u.UserID > maxUserID {
			maxUserID = u.UserID
		}
		s.users[u.Username] = u
	}

	// 2. Load characters
	charRows, err := s.db.QueryContext(ctx, `
		SELECT char_id, user_id, char_uuid, name, level, exp, cash, golden, silver, thew, avatar_id, vip_level, elo, created_at
		FROM characters
	`)
	if err != nil {
		return fmt.Errorf("query characters: %w", err)
	}
	defer charRows.Close()

	var maxCharID uint32 = 10000
	for charRows.Next() {
		var cid, uid, avatar int64
		var lvl, vip int16
		c := &Character{}
		if err := charRows.Scan(
			&cid, &uid, &c.CharUuid, &c.Name, &lvl, &c.Exp, &c.Cash, &c.Golden, &c.Silver,
			&c.Thew, &avatar, &vip, &c.Elo, &c.Created,
		); err != nil {
			return fmt.Errorf("scan character: %w", err)
		}
		c.CharID = uint32(cid)
		c.UserID = uint32(uid)
		c.Level = uint8(lvl)
		c.AvatarID = uint32(avatar)
		c.VipLevel = uint8(vip)
		if c.CharID > maxCharID {
			maxCharID = c.CharID
		}
		s.characters[c.CharID] = c
		s.userChars[c.UserID] = append(s.userChars[c.UserID], c.CharID)
	}

	// 3. Load tanks
	tankRows, err := s.db.QueryContext(ctx, `
		SELECT tank_uuid, char_id, tank_id, tank_level, tank_exp, stth_level, stth_count,
		       ext_flag, external_id, halo_id, war_count, week_war_count, cont_type, exist_time,
		       proficiency_val, battle_gains, tal_page_uuid, EXTRACT(EPOCH FROM created_at)::BIGINT
		FROM character_tanks
	`)
	if err != nil {
		return fmt.Errorf("query tanks: %w", err)
	}
	defer tankRows.Close()

	tankCount := 0
	for tankRows.Next() {
		var tankUuid, talPageUuid string
		var cid, tid, extFlag, extID, haloID, warCount, weekWarCount, existTime, profVal, ownTime int64
		var lvl, stthLvl, stthCnt, contType int16
		var exp uint32
		var gains int32

		if err := tankRows.Scan(
			&tankUuid, &cid, &tid, &lvl, &exp, &stthLvl, &stthCnt,
			&extFlag, &extID, &haloID, &warCount, &weekWarCount, &contType, &existTime,
			&profVal, &gains, &talPageUuid, &ownTime,
		); err != nil {
			return fmt.Errorf("scan tank: %w", err)
		}

		if c, ok := s.characters[uint32(cid)]; ok {
			c.Tanks = append(c.Tanks, PlayerTank{
				TankUuid:       tankUuid,
				TankID:         uint32(tid),
				TankLevel:      uint8(lvl),
				TankExp:        exp,
				ExtFlag:        uint32(extFlag),
				StthLevel:      uint8(stthLvl),
				ExternalID:     uint32(extID),
				WarCount:       uint32(warCount),
				WeekWarCount:   uint32(weekWarCount),
				ContType:       uint8(contType),
				ExistTime:      uint32(existTime),
				HaloID:         uint32(haloID),
				OwnTime:        uint32(ownTime),
				StthCount:      uint8(stthCnt),
				TalPageUuid:    talPageUuid,
				ProficiencyVal: uint32(profVal),
				BattleGains:    gains,
			})
			tankCount++
		}
	}

	// 4. Load items
	itemRows, err := s.db.QueryContext(ctx, `
		SELECT item_uuid, char_id, cont_type, slot_no, template_id, count, level, up_level,
		       exp, rank, ext_flag, life_time, create_time
		FROM character_items
	`)
	if err != nil {
		return fmt.Errorf("query items: %w", err)
	}
	defer itemRows.Close()

	itemCount := 0
	for itemRows.Next() {
		var itemUuid string
		var cid, tpltID, extFlag, lifeTime, createTime int64
		var contType, slotNo, level, upLevel, rank int16
		var count, exp int32

		if err := itemRows.Scan(
			&itemUuid, &cid, &contType, &slotNo, &tpltID, &count, &level, &upLevel,
			&exp, &rank, &extFlag, &lifeTime, &createTime,
		); err != nil {
			return fmt.Errorf("scan item: %w", err)
		}

		if c, ok := s.characters[uint32(cid)]; ok {
			c.Items = append(c.Items, PlayerItem{
				ItemUuid:   itemUuid,
				ContType:   uint8(contType),
				SlotNo:     slotNo,
				TemplateID: uint32(tpltID),
				Count:      count,
				Level:      uint8(level),
				UpLevel:    uint8(upLevel),
				Exp:        exp,
				Rank:       uint8(rank),
				ExtFlag:    uint32(extFlag),
				LifeTime:   uint32(lifeTime),
				CreateTime: uint32(createTime),
			})
			itemCount++
		}
	}

	s.nextUserID.Store(maxUserID + 1)
	s.nextCharID.Store(maxCharID + 1)
	log.Printf("[db] 👥 Loaded %d user(s), %d character(s), %d tank(s), %d item(s) from PostgreSQL (next userID=%d, charID=%d)",
		len(s.users), len(s.characters), tankCount, itemCount, maxUserID+1, maxCharID+1)
	return nil
}

// Register creates a new user account if not existing, plus a default starter character.
func (s *Store) Register(username, password string) (*Character, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	// 1. Check user in memory
	u, exists := s.users[username]
	if exists {
		if err := bcrypt.CompareHashAndPassword(u.PassHash, []byte(password)); err != nil {
			return nil, fmt.Errorf("sai mật khẩu")
		}
		// Return active character
		return s.getActiveCharLocked(u.UserID), nil
	}

	// 2. If not in memory and DB available, check DB
	if s.db != nil {
		u = s.fetchUserFromDB(username)
		if u != nil {
			if err := bcrypt.CompareHashAndPassword(u.PassHash, []byte(password)); err != nil {
				return nil, fmt.Errorf("sai mật khẩu")
			}
			s.users[username] = u
			return s.getActiveCharLocked(u.UserID), nil
		}
	}

	// 3. Create new user
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return nil, err
	}

	userID := s.nextUserID.Add(1) - 1
	charID := s.nextCharID.Add(1) - 1
	charUuid := generateUUID()
	nowSec := uint32(time.Now().Unix())

	newUser := &User{
		UserID:   userID,
		Username: username,
		PassHash: hash,
		Status:   0,
		Created:  time.Now(),
	}

	// 5 Starter tanks chuẩn của BangBang (Gundam, Thép, Panda, Spider, Hulk)
	// Tank 10000019 (Gundam) là tank chủ chiến mặc định (ext_flag = 2)
	starterTanks := []uint32{10000019, 10000001, 10000003, 10000008, 10000002}
	var tanks []PlayerTank
	for i, tid := range starterTanks {
		extFlag := uint32(0)
		if i == 0 {
			extFlag = 2 // bit 2 = JOIN_BATTLE (Xe xuất trận mặc định)
		}
		tanks = append(tanks, PlayerTank{
			TankUuid:       generateUUID(),
			TankID:         tid,
			TankLevel:      1,
			TankExp:        0,
			StthLevel:      0,
			StthCount:      0,
			ExtFlag:        extFlag,
			ExternalID:     0,
			HaloID:         0,
			ContType:       0,
			OwnTime:        nowSec,
			ProficiencyVal: 0,
		})
	}

	// 11 Starter items
	starterItems := []struct {
		cont  uint8
		slot  int16
		tplt  uint32
		count int32
	}{
		{2, 0, 8000111, 2},  // Rương tank ngẫu nhiên
		{2, 1, 2004393, 50}, // 10 xu khóa
		{2, 2, 2320004, 5},  // Thẻ tăng Vàng 20 lần
		{2, 3, 2001016, 20}, // Pháo hoa
		{2, 4, 2100001, 50}, // Loa nhỏ
		{2, 5, 2600001, 10}, // Bình phun

		{3, 0, 4050011, 100}, // Lõi nguyên năng
		{3, 1, 4700001, 200}, // Khối huyền thiết
		{3, 2, 4700011, 200}, // Pin cao năng
		{3, 3, 4050013, 50},  // Hợp kim nano
		{3, 4, 8000005, 500}, // Vàng xu
	}

	var items []PlayerItem
	for _, it := range starterItems {
		items = append(items, PlayerItem{
			ItemUuid:   generateUUID(),
			ContType:   it.cont,
			SlotNo:     it.slot,
			TemplateID: it.tplt,
			Count:      it.count,
			Level:      1,
			UpLevel:    0,
			Rank:       1,
			LifeTime:   0,
			CreateTime: nowSec,
		})
	}

	newChar := &Character{
		CharID:   charID,
		UserID:   userID,
		CharUuid: charUuid,
		Name:     username,
		Level:    1,
		Exp:      0,
		Cash:     10000,
		Golden:   5000,
		Silver:   50000,
		Thew:     200,
		AvatarID: 0,
		VipLevel: 0,
		Elo:      1000,
		Tanks:    tanks,
		Items:    items,
		Created:  time.Now(),
	}

	if s.db != nil {
		if err := s.saveNewUserAndCharToDB(newUser, newChar); err != nil {
			return nil, fmt.Errorf("lưu database thất bại: %w", err)
		}
		log.Printf("[db] 💾 Tạo User %s (ID=%d) & Character %s (CharID=%d) lưu vào PostgreSQL", username, userID, newChar.Name, charID)
	}

	s.users[username] = newUser
	s.characters[charID] = newChar
	s.userChars[userID] = append(s.userChars[userID], charID)

	return newChar, nil
}

func (s *Store) getActiveCharLocked(userID uint32) *Character {
	cids := s.userChars[userID]
	if len(cids) > 0 {
		return s.characters[cids[0]]
	}
	return nil
}

func (s *Store) fetchUserFromDB(username string) *User {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	var uid int64
	var st int16
	u := &User{}
	err := s.db.QueryRowContext(ctx, "SELECT user_id, pass_hash, status, created_at FROM users WHERE username = $1", username).
		Scan(&uid, &u.PassHash, &st, &u.Created)
	if err != nil {
		return nil
	}
	u.UserID = uint32(uid)
	u.Username = username
	u.Status = uint8(st)
	return u
}

func (s *Store) saveNewUserAndCharToDB(u *User, c *Character) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()

	_, err = tx.ExecContext(ctx, `
		INSERT INTO users (user_id, username, pass_hash, status, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, NOW())
	`, u.UserID, u.Username, u.PassHash, u.Status, u.Created)
	if err != nil {
		return fmt.Errorf("insert user: %w", err)
	}

	_, err = tx.ExecContext(ctx, `
		INSERT INTO characters (char_id, user_id, char_uuid, name, level, exp, cash, golden, silver, thew, avatar_id, vip_level, elo, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, NOW())
	`, c.CharID, c.UserID, c.CharUuid, c.Name, c.Level, c.Exp, c.Cash, c.Golden, c.Silver, c.Thew, c.AvatarID, c.VipLevel, c.Elo, c.Created)
	if err != nil {
		return fmt.Errorf("insert character: %w", err)
	}

	for _, t := range c.Tanks {
		_, err = tx.ExecContext(ctx, `
			INSERT INTO character_tanks (
				tank_uuid, char_id, tank_id, tank_level, tank_exp, stth_level, stth_count,
				ext_flag, external_id, halo_id, war_count, week_war_count, cont_type, exist_time,
				proficiency_val, battle_gains, tal_page_uuid, created_at, updated_at
			) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, NOW(), NOW())
		`, t.TankUuid, c.CharID, t.TankID, t.TankLevel, t.TankExp, t.StthLevel, t.StthCount,
			t.ExtFlag, t.ExternalID, t.HaloID, t.WarCount, t.WeekWarCount, t.ContType, t.ExistTime,
			t.ProficiencyVal, t.BattleGains, t.TalPageUuid)
		if err != nil {
			return fmt.Errorf("insert character tank: %w", err)
		}
	}

	for _, it := range c.Items {
		_, err = tx.ExecContext(ctx, `
			INSERT INTO character_items (
				item_uuid, char_id, cont_type, slot_no, template_id, count, level, up_level,
				exp, rank, ext_flag, life_time, create_time, created_at, updated_at
			) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW(), NOW())
		`, it.ItemUuid, c.CharID, it.ContType, it.SlotNo, it.TemplateID, it.Count, it.Level, it.UpLevel,
			it.Exp, it.Rank, it.ExtFlag, it.LifeTime, it.CreateTime)
		if err != nil {
			return fmt.Errorf("insert character item: %w", err)
		}
	}

	return tx.Commit()
}

// GetUser retrieves User by username.
func (s *Store) GetUser(username string) *User {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.users[username]
}

// GetActiveCharacterByUsername retrieves active character for a user.
func (s *Store) GetActiveCharacterByUsername(username string) *Character {
	s.mu.RLock()
	defer s.mu.RUnlock()
	u, ok := s.users[username]
	if !ok {
		return nil
	}
	return s.getActiveCharLocked(u.UserID)
}

// GetCharacter retrieves character by charID.
func (s *Store) GetCharacter(charID uint32) *Character {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.characters[charID]
}

// GetUserCharacters retrieves all characters for a user.
func (s *Store) GetUserCharacters(userID uint32) []*Character {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var list []*Character
	for _, cid := range s.userChars[userID] {
		if c, ok := s.characters[cid]; ok {
			list = append(list, c)
		}
	}
	return list
}

// FindCharacterByIdentity finds a character by UUID, numeric ID, or name.
func (s *Store) FindCharacterByIdentity(identity string) *Character {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if identity == "" {
		return nil
	}
	// Try parsing as uint32 charID
	if cid, err := strconv.ParseUint(identity, 10, 32); err == nil {
		if c, ok := s.characters[uint32(cid)]; ok {
			return c
		}
	}
	// Try matching CharUuid, Name, or string form of CharID
	for _, c := range s.characters {
		if c.CharUuid == identity || strconv.FormatUint(uint64(c.CharID), 10) == identity || c.Name == identity {
			return c
		}
	}
	// Try extracting digits if identity has a prefix like "char-10001"
	digits := ""
	for _, ch := range identity {
		if ch >= '0' && ch <= '9' {
			digits += string(ch)
		}
	}
	if digits != "" {
		if cid, err := strconv.ParseUint(digits, 10, 32); err == nil {
			if c, ok := s.characters[uint32(cid)]; ok {
				return c
			}
		}
	}
	// If only 1 character exists in entire store, fallback to it
	if len(s.characters) == 1 {
		for _, c := range s.characters {
			return c
		}
	}
	return nil
}

// LevelUpTank increases tank level (1 -> 6).
func (s *Store) LevelUpTank(charID uint32, tankUUID string) (*PlayerTank, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return nil, fmt.Errorf("character %d not found", charID)
	}

	var target *PlayerTank
	for i := range c.Tanks {
		if c.Tanks[i].TankUuid == tankUUID {
			target = &c.Tanks[i]
			break
		}
	}
	if target == nil {
		return nil, fmt.Errorf("tank %s not found", tankUUID)
	}

	if target.TankLevel >= 6 {
		return nil, fmt.Errorf("tank đã đạt cấp tối đa (Level 6)")
	}

	target.TankLevel++
	target.StthLevel = 0

	if s.db != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		s.db.ExecContext(ctx, `
			UPDATE character_tanks 
			SET tank_level = $1, stth_level = $2, updated_at = NOW() 
			WHERE tank_uuid = $3
		`, target.TankLevel, target.StthLevel, target.TankUuid)
	}

	return target, nil
}

// StrengthenTank increases strengthen level.
func (s *Store) StrengthenTank(charID uint32, tankUUID string) (*PlayerTank, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return nil, fmt.Errorf("character %d not found", charID)
	}

	var target *PlayerTank
	for i := range c.Tanks {
		if c.Tanks[i].TankUuid == tankUUID {
			target = &c.Tanks[i]
			break
		}
	}
	if target == nil {
		return nil, fmt.Errorf("tank %s not found", tankUUID)
	}

	target.StthLevel++
	target.StthCount++

	if s.db != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		s.db.ExecContext(ctx, `
			UPDATE character_tanks 
			SET stth_level = $1, stth_count = $2, updated_at = NOW() 
			WHERE tank_uuid = $3
		`, target.StthLevel, target.StthCount, target.TankUuid)
	}

	return target, nil
}

// GetPlayerItems retrieves items in a container for a character.
func (s *Store) GetPlayerItems(charID uint32, contType uint8) []PlayerItem {
	s.mu.RLock()
	defer s.mu.RUnlock()

	c := s.characters[charID]
	if c == nil {
		return nil
	}

	var result []PlayerItem
	for _, it := range c.Items {
		if contType == 0 || it.ContType == contType {
			result = append(result, it)
		}
	}
	return result
}

// UseItem consumes an item from inventory.
func (s *Store) UseItem(charID uint32, contType uint8, slotNo int16, count int32) (*PlayerItem, *Character, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return nil, nil, fmt.Errorf("character %d not found", charID)
	}

	var itemIdx = -1
	for i := range c.Items {
		if c.Items[i].ContType == contType && c.Items[i].SlotNo == slotNo {
			itemIdx = i
			break
		}
	}

	if itemIdx < 0 {
		return nil, nil, fmt.Errorf("vật phẩm không tồn tại ở ô %d", slotNo)
	}

	it := &c.Items[itemIdx]
	if it.Count < count {
		count = it.Count
	}
	it.Count -= count

	if it.TemplateID == 2004393 { // 10 xu khóa
		c.Golden += count * 10
	} else if it.TemplateID == 8000005 { // Vàng xu
		c.Silver += count * 50
	}

	if s.db != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if it.Count <= 0 {
			s.db.ExecContext(ctx, "DELETE FROM character_items WHERE char_id = $1 AND cont_type = $2 AND slot_no = $3",
				charID, contType, slotNo)
			c.Items = append(c.Items[:itemIdx], c.Items[itemIdx+1:]...)
			it = nil
		} else {
			s.db.ExecContext(ctx, "UPDATE character_items SET count = $1, updated_at = NOW() WHERE item_uuid = $2",
				it.Count, it.ItemUuid)
		}
		s.db.ExecContext(ctx, "UPDATE characters SET cash = $1, golden = $2, silver = $3, updated_at = NOW() WHERE char_id = $4",
			c.Cash, c.Golden, c.Silver, c.CharID)
	} else {
		if it.Count <= 0 {
			c.Items = append(c.Items[:itemIdx], c.Items[itemIdx+1:]...)
			it = nil
		}
	}

	return it, c, nil
}

// CleanUpCont sorts and defragments items in a container.
func (s *Store) CleanUpCont(charID uint32, contType uint8) []PlayerItem {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return nil
	}

	var slot int16 = 0
	var updated []PlayerItem
	for i := range c.Items {
		if c.Items[i].ContType == contType {
			c.Items[i].SlotNo = slot
			updated = append(updated, c.Items[i])
			if s.db != nil {
				ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
				s.db.ExecContext(ctx, "UPDATE character_items SET slot_no = $1 WHERE item_uuid = $2", slot, c.Items[i].ItemUuid)
				cancel()
			}
			slot++
		}
	}
	return updated
}

// CreateSession creates a session for a character.
func (s *Store) CreateSession(c *Character) *Session {
	sessKey := s.nextSess.Add(1) - 1
	sess := &Session{
		SessionKey: sessKey,
		UserID:     c.UserID,
		CharID:     c.CharID,
		Character:  c,
		ExpiresAt:  time.Now().Add(24 * time.Hour),
	}
	s.mu.Lock()
	// Invalidate any older sessions for this character
	for k, oldSess := range s.sessions {
		if oldSess.CharID == c.CharID {
			delete(s.sessions, k)
		}
	}
	s.sessions[sessKey] = sess
	s.mu.Unlock()
	return sess
}

// GetSession retrieves a session by key.
func (s *Store) GetSession(key uint32) *Session {
	s.mu.RLock()
	defer s.mu.RUnlock()
	sess, ok := s.sessions[key]
	if !ok || time.Now().After(sess.ExpiresAt) {
		return nil
	}
	return sess
}

// Close closes DB connection.
func (s *Store) Close() error {
	if s.db != nil {
		return s.db.Close()
	}
	return nil
}

// ChangeBattleTank sets active battle tank (ext_flag = 2) and clears it from all other tanks.
func (s *Store) ChangeBattleTank(charID uint32, tankUUID string) (oldTank *PlayerTank, newTank *PlayerTank, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return nil, nil, fmt.Errorf("character %d not found", charID)
	}

	var foundNew *PlayerTank
	for i := range c.Tanks {
		if c.Tanks[i].TankUuid == tankUUID {
			foundNew = &c.Tanks[i]
		}
	}
	if foundNew == nil {
		return nil, nil, fmt.Errorf("tank %s not found", tankUUID)
	}

	for i := range c.Tanks {
		if c.Tanks[i].TankUuid != tankUUID && (c.Tanks[i].ExtFlag&2) != 0 {
			c.Tanks[i].ExtFlag &= ^uint32(2)
			copied := c.Tanks[i]
			oldTank = &copied
		}
	}

	foundNew.ExtFlag |= 2
	copiedNew := *foundNew
	newTank = &copiedNew

	if s.db != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		s.db.ExecContext(ctx, `UPDATE character_tanks SET ext_flag = ext_flag & ~2, updated_at = NOW() WHERE char_id = $1 AND (ext_flag & 2) != 0`, charID)
		s.db.ExecContext(ctx, `UPDATE character_tanks SET ext_flag = ext_flag | 2, updated_at = NOW() WHERE char_id = $1 AND tank_uuid = $2`, charID, tankUUID)
	}

	return oldTank, newTank, nil
}

type ShopOfferInfo struct {
	IsTank        bool
	ItemID        uint32
	ContainerType uint8
}

// BuyGoods processes purchases from the shop, deducts coins, and adds tanks or items.
func (s *Store) BuyGoods(charID uint32, goodsID uint32, coinType uint32, price int32, count int32, offer *ShopOfferInfo) (*Character, *PlayerTank, *PlayerItem, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return nil, nil, nil, fmt.Errorf("character %d not found", charID)
	}

	if count <= 0 {
		count = 1
	}
	totalCost := price * count

	// 1. Kiểm tra và trừ tiền (CoinType: 1: Xu, 2: Bạc, 3: Xu Khóa)
	switch coinType {
	case 1:
		if c.Cash < totalCost {
			return nil, nil, nil, fmt.Errorf("không đủ Xu")
		}
		c.Cash -= totalCost
	case 2:
		if c.Silver < totalCost {
			return nil, nil, nil, fmt.Errorf("không đủ Bạc")
		}
		c.Silver -= totalCost
	case 3:
		if c.Golden < totalCost {
			return nil, nil, nil, fmt.Errorf("không đủ Xu Khóa")
		}
		c.Golden -= totalCost
	default:
		// Fallback check
		if c.Silver >= totalCost {
			c.Silver -= totalCost
		} else if c.Golden >= totalCost {
			c.Golden -= totalCost
		} else if c.Cash >= totalCost {
			c.Cash -= totalCost
		}
	}

	var addedTank *PlayerTank
	var addedItem *PlayerItem
	nowSec := uint32(time.Now().Unix())

	isTank := false
	if offer != nil && offer.IsTank {
		isTank = true
	} else if goodsID >= 902000000 && goodsID <= 902002000 {
		isTank = true
	}

	if isTank {
		tankID := uint32(0)
		if offer != nil && offer.ItemID > 0 {
			tankID = offer.ItemID
		} else {
			tankID = 10000019
		}

		// Kiểm tra nếu đã có tank này
		for _, t := range c.Tanks {
			if t.TankID == tankID {
				return nil, nil, nil, fmt.Errorf("bạn đã sở hữu xe tank này")
			}
		}

		newTank := PlayerTank{
			TankUuid:  generateUUID(),
			TankID:    tankID,
			TankLevel: 1,
			ExtFlag:   0,
			OwnTime:   nowSec,
		}
		c.Tanks = append(c.Tanks, newTank)
		addedTank = &newTank

		if s.db != nil {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			s.db.ExecContext(ctx, `
				INSERT INTO character_tanks (
					tank_uuid, char_id, tank_id, tank_level, tank_exp, stth_level, stth_count,
					ext_flag, external_id, halo_id, war_count, week_war_count, cont_type, exist_time,
					proficiency_val, battle_gains, tal_page_uuid, created_at, updated_at
				) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, NOW(), NOW())
			`, newTank.TankUuid, c.CharID, newTank.TankID, newTank.TankLevel, newTank.TankExp, newTank.StthLevel, newTank.StthCount,
				newTank.ExtFlag, newTank.ExternalID, newTank.HaloID, newTank.WarCount, newTank.WeekWarCount, newTank.ContType, newTank.ExistTime,
				newTank.ProficiencyVal, newTank.BattleGains, newTank.TalPageUuid)
		}
	} else {
		itemID := uint32(0)
		contType := uint8(2)
		if offer != nil && offer.ItemID > 0 {
			itemID = offer.ItemID
			if offer.ContainerType > 0 {
				contType = offer.ContainerType
			}
		}

		usedSlots := make(map[int16]bool)
		for _, it := range c.Items {
			if it.ContType == contType {
				usedSlots[it.SlotNo] = true
			}
		}
		slotNo := int16(0)
		for s := int16(0); s < 100; s++ {
			if !usedSlots[s] {
				slotNo = s
				break
			}
		}

		newItem := PlayerItem{
			ItemUuid:   generateUUID(),
			ContType:   contType,
			SlotNo:     slotNo,
			TemplateID: itemID,
			Count:      count,
			Level:      1,
			Rank:       1,
			CreateTime: nowSec,
		}
		c.Items = append(c.Items, newItem)
		addedItem = &newItem

		if s.db != nil {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			s.db.ExecContext(ctx, `
				INSERT INTO character_items (
					item_uuid, char_id, cont_type, slot_no, template_id, count, level, up_level,
					exp, rank, ext_flag, life_time, create_time, created_at, updated_at
				) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW(), NOW())
			`, newItem.ItemUuid, c.CharID, newItem.ContType, newItem.SlotNo, newItem.TemplateID, newItem.Count, newItem.Level, newItem.UpLevel,
				newItem.Exp, newItem.Rank, newItem.ExtFlag, newItem.LifeTime, newItem.CreateTime)
		}
	}

	if s.db != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		s.db.ExecContext(ctx, `
			UPDATE characters 
			SET cash = $1, golden = $2, silver = $3, updated_at = NOW() 
			WHERE char_id = $4
		`, c.Cash, c.Golden, c.Silver, c.CharID)
	}

	return c, addedTank, addedItem, nil
}

func generateUUID() string {
	b := make([]byte, 16)
	rand.Read(b)
	return hex.EncodeToString(b)
}
