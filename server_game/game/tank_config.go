package game

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"sync"
)

// SkillSlotConfig holds combat parameters for a single skill slot (E, Space, Passive, R).
type SkillSlotConfig struct {
	SkillID     uint32
	CooldownMS  uint32
	MPCost      int32
	BulletSpeed int16
	Damage      int32
	Range       float32
	Type        string  // "projectile", "aoe", "buff", "dash", "beam"
	DamageMult  float64 // damage multiplier (0 = default 1.5x for skills)
}

// NormalBulletConfig holds parameters for a tank's basic attack (slot 0).
type NormalBulletConfig struct {
	Template uint32 // Skill/bullet template ID from server/public/godot/a/e/index.json (normal_bullets)
	Speed    int16
	Damage   int32
	Range    int16 // Max range in pixels (0 = unlimited / mouse dest)
}

// TankConfig holds per-tank stats, basic attack, and skill definitions.
type TankConfig struct {
	TankID       uint32
	Name         string
	HP           int32
	MP           int32
	MoveSpeed    int16
	FireRateMS   int16
	NormalBullet NormalBulletConfig
	Skills       [4]SkillSlotConfig // [SkillE, SkillSpace, Passive, SkillR]
	Combat       CombatStats        // Base combat stats (ATK, DEF, Pierce)
}

const (
	defaultTankHP          int32 = 1000
	defaultTankMP          int32 = 100
	defaultTankMoveSpeed   int16 = 200
	defaultTankFireRateMS  int16 = 500
	defaultBulletSpeed     int16 = 600
	defaultBulletDamage    int32 = 100
	defaultNormalTemplate  uint32 = 1
)

// tankOverrides defines per-tank custom overrides when needed; stats (HP, MoveSpeed, FireRateMS, Combat)
// come directly from TankUpTemplate_table.xml (tank_stats.go).
var tankOverrides = map[uint32]TankConfig{
	10000001: {
		TankID: 10000001,
		Name:   "Steel",
	},
	10000002: {
		TankID: 10000002,
		Name:   "Flying Wing",
	},
	10000003: {
		TankID: 10000003,
		Name:   "Po",
	},
	10000019: {
		TankID: 10000019,
		Name:   "Gundam",
		NormalBullet: NormalBulletConfig{
			Template: 302600,
			Range:    580,
		},
	},
	10000036: {
		TankID: 10000036,
		Name:   "Wukong",
		NormalBullet: NormalBulletConfig{
			Template: 310100,
			Range:    336,
		},
	},
}

type godotFXIndex struct {
	NormalBullets []uint32                   `json:"normal_bullets"`
	Skills        map[string]json.RawMessage `json:"skills"`
}

var (
	tankConfigMu    sync.RWMutex
	tankConfigCache = make(map[uint32]*TankConfig)
	godotNormalSet  = make(map[uint32]bool)
	godotSkillSet   = make(map[uint32]bool)
)

// InitTankConfigs loads bullet/skill template IDs from server/public/godot/a/e/index.json
// and builds the per-tank configuration map.
func InitTankConfigs(staticDir string) {
	fxPath := filepath.Join(staticDir, "godot", "a", "e", "index.json")
	normalSet := make(map[uint32]bool)
	skillSet := make(map[uint32]bool)

	if data, err := os.ReadFile(fxPath); err != nil {
		log.Printf("[tank_config] warning: cannot read %s: %v (using fallback templates)", fxPath, err)
	} else {
		var fx godotFXIndex
		if err := json.Unmarshal(data, &fx); err != nil {
			log.Printf("[tank_config] warning: invalid %s: %v", fxPath, err)
		} else {
			for _, id := range fx.NormalBullets {
				normalSet[id] = true
			}
			for k := range fx.Skills {
				if id, err := strconv.ParseUint(k, 10, 32); err == nil {
					skillSet[uint32(id)] = true
				}
			}
			log.Printf("[tank_config] loaded %d normal_bullets and %d skills from %s", len(normalSet), len(skillSet), fxPath)
		}
	}

	cache := make(map[uint32]*TankConfig, len(TankSkillsMap))
	for tankID := range TankSkillsMap {
		cache[tankID] = buildTankConfig(tankID, normalSet)
	}
	for tankID := range tankOverrides {
		if _, exists := cache[tankID]; !exists {
			cache[tankID] = buildTankConfig(tankID, normalSet)
		}
	}

	tankConfigMu.Lock()
	godotNormalSet = normalSet
	godotSkillSet = skillSet
	tankConfigCache = cache
	tankConfigMu.Unlock()
}

// GetTankConfig returns the resolved TankConfig for tankID (never nil).
func GetTankConfig(tankID uint32) *TankConfig {
	tankConfigMu.RLock()
	cfg, ok := tankConfigCache[tankID]
	normalSet := godotNormalSet
	tankConfigMu.RUnlock()
	if ok && cfg != nil {
		return cfg
	}
	return buildTankConfig(tankID, normalSet)
}

func buildTankConfig(tankID uint32, normalSet map[uint32]bool) *TankConfig {
	skillIDs := GetTankSkills(tankID)
	cfg := &TankConfig{
		TankID:     tankID,
		Name:       fmt.Sprintf("Tank_%d", tankID),
		HP:         defaultTankHP,
		MP:         defaultTankMP,
		MoveSpeed:  defaultTankMoveSpeed,
		FireRateMS: defaultTankFireRateMS,
		NormalBullet: NormalBulletConfig{
			Template: resolveNormalBulletTemplate(skillIDs, normalSet),
			Speed:    defaultBulletSpeed,
			Damage:   defaultBulletDamage,
		},
	}

	// Apply SkillTemplate range/speed for normal bullet
	if st, ok := GetSkillTemplate(cfg.NormalBullet.Template); ok {
		if st.FlyRange > 0 && st.FlyRange < 30000 {
			cfg.NormalBullet.Range = int16(st.FlyRange)
		} else if st.Range > 0 && st.Range < 30000 {
			cfg.NormalBullet.Range = int16(st.Range)
		}
		if st.FlyRange > 0 && st.LifeTime > 0 {
			if spd := st.FlyRange * 1000 / st.LifeTime; spd > 0 && spd < 30000 {
				cfg.NormalBullet.Speed = int16(spd)
			}
		}
	}

	// Apply real stats from TankUpTemplate_table.xml (level 1)
	if base := GetTankBaseStats(tankID); base != nil {
		cfg.HP = base.HP
		if base.MP > 0 {
			cfg.MP = base.MP
		}
		cfg.MoveSpeed = int16(base.MoveSpeed)
		cfg.FireRateMS = int16(base.FireRateMS)
		cfg.Combat = CombatStats{
			Attack:    float64(base.Attack),
			EnergyAtk: float64(base.EnergyAtk),
			Armor:     float64(base.Armor),
			EnergyDef: float64(base.EnergyDef),
			Pierce:    float64(base.Pierce),
			EnergyPen: float64(base.EnergyPen),
		}
		cfg.NormalBullet.Damage = base.Attack // base ATK as bullet damage
	}

	for i := 0; i < 4; i++ {
		sid := skillIDs[i]
		slotCfg := SkillSlotConfig{
			SkillID:     sid,
			BulletSpeed: defaultBulletSpeed,
		}
		if st, ok := GetSkillTemplate(sid); ok {
			if st.CoolTime > 0 {
				slotCfg.CooldownMS = st.CoolTime
			}
			if st.MpCost > 0 {
				slotCfg.MPCost = st.MpCost
			}
			if st.Range > 0 {
				slotCfg.Range = float32(st.Range)
			}
			if st.FlyRange > 0 && st.LifeTime > 0 {
				if spd := int32(st.FlyRange) * 1000 / st.LifeTime; spd > 0 && spd < 30000 {
					slotCfg.BulletSpeed = int16(spd)
				}
			}
		}
		if mult := GetEffectAddVal(sid, 0); mult > 0 {
			slotCfg.DamageMult = mult
		}
		cfg.Skills[i] = slotCfg
	}

	if ov, ok := tankOverrides[tankID]; ok {
		applyTankOverride(cfg, &ov)
	}
	return cfg
}

func applyTankOverride(dst, ov *TankConfig) {
	if ov.Name != "" {
		dst.Name = ov.Name
	}
	if ov.HP > 0 {
		dst.HP = ov.HP
	}
	if ov.MP > 0 {
		dst.MP = ov.MP
	}
	if ov.MoveSpeed > 0 {
		dst.MoveSpeed = ov.MoveSpeed
	}
	if ov.FireRateMS > 0 {
		dst.FireRateMS = ov.FireRateMS
	}
	if ov.NormalBullet.Template != 0 {
		dst.NormalBullet.Template = ov.NormalBullet.Template
	}
	if ov.NormalBullet.Speed > 0 {
		dst.NormalBullet.Speed = ov.NormalBullet.Speed
	}
	if ov.NormalBullet.Damage > 0 {
		dst.NormalBullet.Damage = ov.NormalBullet.Damage
	}
	if ov.NormalBullet.Range > 0 {
		dst.NormalBullet.Range = ov.NormalBullet.Range
	}
	for i := 0; i < 4; i++ {
		s := ov.Skills[i]
		if s.SkillID != 0 {
			dst.Skills[i].SkillID = s.SkillID
		}
		if s.CooldownMS > 0 {
			dst.Skills[i].CooldownMS = s.CooldownMS
		}
		if s.MPCost > 0 {
			dst.Skills[i].MPCost = s.MPCost
		}
		if s.BulletSpeed > 0 {
			dst.Skills[i].BulletSpeed = s.BulletSpeed
		}
		if s.Damage > 0 {
			dst.Skills[i].Damage = s.Damage
		}
		if s.Range > 0 {
			dst.Skills[i].Range = s.Range
		}
		if s.Type != "" {
			dst.Skills[i].Type = s.Type
		}
	}
}

// resolveNormalBulletTemplate derives the tank's basic attack template ID from its skill IDs
// by matching entries in server/public/godot/a/e/index.json (normal_bullets).
// Most tanks follow the convention: skill 363201 -> normal bullet 363100, 334021 -> 334010, 302701 -> 302600.
func resolveNormalBulletTemplate(skills [4]uint32, normalSet map[uint32]bool) uint32 {
	if len(normalSet) == 0 {
		return defaultNormalTemplate
	}
	for _, sid := range skills {
		if sid == 0 {
			continue
		}
		// Exact base-100 / base-1000 rounding candidates used in e/index.json normal_bullets
		candidates := []uint32{
			(sid/1000)*1000 + 100,
			(sid/1000)*1000 + 10,
			(sid / 10) * 10,
			(sid/100)*100 - 100,
		}
		for _, c := range candidates {
			if normalSet[c] {
				return c
			}
		}
	}
	return defaultNormalTemplate
}

// SkillArray returns [4]uint32 skill IDs [SkillE, SkillSpace, Passive, SkillR].
func (c *TankConfig) SkillArray() [4]uint32 {
	return [4]uint32{
		c.Skills[0].SkillID,
		c.Skills[1].SkillID,
		c.Skills[2].SkillID,
		c.Skills[3].SkillID,
	}
}

// SkillForSlot returns (templateID, bulletSpeed) for the given request slotNo (0=normal, 1=E, 2=Space, 3/10=R).
func (c *TankConfig) SkillForSlot(slotNo uint8) (uint32, int16) {
	switch slotNo {
	case 0:
		tpl := c.NormalBullet.Template
		if tpl == 0 {
			tpl = defaultNormalTemplate
		}
		spd := c.NormalBullet.Speed
		if spd <= 0 {
			spd = defaultBulletSpeed
		}
		return tpl, spd
	case 1:
		return c.skillSlotTemplate(0)
	case 2:
		return c.skillSlotTemplate(1)
	case 3, 10:
		return c.skillSlotTemplate(3)
	default:
		return defaultNormalTemplate, defaultBulletSpeed
	}
}

func (c *TankConfig) skillSlotTemplate(idx int) (uint32, int16) {
	tpl := c.Skills[idx].SkillID
	if tpl == 0 {
		tpl = defaultNormalTemplate
	}
	spd := c.Skills[idx].BulletSpeed
	if spd <= 0 {
		spd = defaultBulletSpeed
	}
	return tpl, spd
}
