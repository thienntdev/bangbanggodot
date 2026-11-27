package game

import (
	"math"
	"sync"
)

// FireEvent represents a single projectile emitted by an actor (m_fireVec in 1564).
type FireEvent struct {
	Template   uint32
	StartX     int16
	StartY     int16
	DestX      int16
	DestY      int16
	Speed      int16
	DamageMult float64 // damage multiplier (0 = use 1.0); skill bullets can be 1.5x, 2.0x, etc.
	School     string  // "physical" or "energy" (empty = infer from EffectTemplate.HarmType)
	Basic      bool    // true = basic attack (eligible for crit)
	TargetID   uint32  // non-zero = homing missile tracking this target ID
}

// AreaHitEvent represents an immediate melee/cone/circle/beam AOE hit evaluated on the server.
type AreaHitEvent struct {
	Shape      string   // "circle", "cone", "rect"
	Template   uint32   // skill/effect template ID for kill attribution
	StartX     int16
	StartY     int16
	DestX      int16
	DestY      int16
	Radius     float64  // circle/cone radius or rect length
	HalfWidth  float64  // rect half-width (e.g. 36 for 72px laser)
	AngleDeg   float64  // cone full angle in degrees (e.g. 180)
	School     string   // "physical" or "energy"
	DamageMult float64
	Basic      bool     // true = eligible for crit
	ForceCrit  bool     // true = guaranteed critical hit (e.g. Wukong empowered sweep)
	Lifesteal  float64  // fraction of damage healed to caster (e.g. 0.25)
	OnHitBuffs []uint32 // buff template IDs applied to each hit enemy
}

// SkillEvent represents a cast/melee/AOE skill visual (m_skillVec in 1564).
type SkillEvent struct {
	Template uint32
	TargetID uint32
	StartX   int16
	StartY   int16
	DestX    int16
	DestY    int16
	Ready    uint8
}

// MoveEvent represents a forced movement / dash / stop (m_moveVec in 1564).
type MoveEvent struct {
	DestX    int16
	DestY    int16
	Speed    int16
	MoveType uint8 // 3=dash/recoil, 5=stop/cast
}

// CooldownEvent triggers a skill cooldown timer on client (msg 1572).
type CooldownEvent struct {
	SlotNo     uint8
	SkillID    uint32
	CooldownMS uint32
}

// BuffEvent adds (1558) or removes (1559) a buff on an actor.
type BuffEvent struct {
	Remove     bool
	TargetID   uint32
	TemplateID uint32
	InstID     uint32
	Stacks     uint8
	DurationMS uint32
}

// SlotSwapEvent replaces a skill slot's active template on client (msg 1579).
type SlotSwapEvent struct {
	SlotNo     uint8
	SkillID    uint32
	CooldownMS uint32
}

// ObjectEvent adds (1556) or removes (via expired_bullets in 1564) a scene object.
// Python: add_object(template, position) → (ident, (1556, body))
// Object IDs use (kind<<26)|serial; kind=4 or 5 for scene objects.
type ObjectEvent struct {
	Remove   bool   // true = remove (send via 1564 expired_bullets)
	Template uint32 // m_tplId (e.g., 310302, 310304, 310305 for Wukong space)
	PosX     int16
	PosY     int16
	Camp     uint8
	OwnerID  uint32
	LifeMS   int // auto-remove after this many ms (0 = no auto-remove)
}

// ShieldEvent adds shield HP to a target actor (fixed Amount or fraction MaxHPPct of MaxHP).
type ShieldEvent struct {
	TargetID uint32
	Amount   int32
	MaxHPPct float64
}

// CooldownPctEvent scales a slot's remaining cooldown by Factor (e.g. 0.75 = -25% remaining CD).
type CooldownPctEvent struct {
	SlotNo  uint8
	SkillID uint32
	Factor  float64
}

// DelayedAction schedules a follow-up ActionResult after DelayMS milliseconds (e.g., windup -> hit).
type DelayedAction struct {
	DelayMS int
	Run     func() ActionResult
}

// ActionResult bundles all scene/protocol outputs produced by a combat hook.
type ActionResult struct {
	Fires     []FireEvent
	AreaHits  []AreaHitEvent
	Skills    []SkillEvent
	Moves     []MoveEvent
	Cooldowns []CooldownEvent
	Buffs     []BuffEvent
	SlotSwaps []SlotSwapEvent
	Objects         []ObjectEvent
	Delayed         []DelayedAction
	ImmuneMS        int64              // grants damage immunity for this duration
	DamageReducePct float64            // grants % damage reduction (0.0-1.0) for DamageReduceMS
	DamageReduceMS  int64              // duration of DamageReducePct
	Shields         []ShieldEvent      // adds shield HP to targets
	CooldownPcts    []CooldownPctEvent // scales remaining slot cooldowns
}

// ActorContext provides an actor's current state and config when executing combat hooks.
type ActorContext struct {
	RoomID  uint32
	ActorID uint32
	TankID  uint32
	Camp    uint8
	PosX    int16
	PosY    int16
	TargetX int16
	TargetY int16
	Config  *TankConfig
	Walls   []WallRect
}

// ActorBehavior defines lifecycle and combat hooks for any battle entity (Tank, Mob, Boss).
// Custom implementations should embed DefaultBehavior so they only override what they need.
type ActorBehavior interface {
	OnSpawn(ctx *ActorContext)
	OnUseSkill(ctx *ActorContext, slotNo uint8, targetID uint32, destX, destY int16) ActionResult
	OnBulletHit(ctx *ActorContext, template uint32, targetID uint32) ActionResult
	OnTakeDamage(ctx *ActorContext, attackerID uint32, damage int32, isSkill bool) ActionResult
	OnTick(ctx *ActorContext, nowMs int64) ActionResult
}

// BehaviorFactory creates a fresh per-match instance of an ActorBehavior.
type BehaviorFactory func() ActorBehavior

var (
	behaviorMu    sync.RWMutex
	tankBehaviors = make(map[uint32]BehaviorFactory)
	npcBehaviors  = make(map[uint32]BehaviorFactory) // Ready for Boss & Mob templates
)

// RegisterTankBehavior registers a custom behavior factory for a TankID (typically called in init()).
func RegisterTankBehavior(tankID uint32, factory BehaviorFactory) {
	behaviorMu.Lock()
	defer behaviorMu.Unlock()
	tankBehaviors[tankID] = factory
}

// RegisterNPCBehavior registers a custom behavior factory for a Mob or Boss template ID.
func RegisterNPCBehavior(npcTemplateID uint32, factory BehaviorFactory) {
	behaviorMu.Lock()
	defer behaviorMu.Unlock()
	npcBehaviors[npcTemplateID] = factory
}

// NewTankBehavior returns a fresh ActorBehavior for tankID, or DefaultBehavior if none is registered.
func NewTankBehavior(tankID uint32) ActorBehavior {
	behaviorMu.RLock()
	factory, ok := tankBehaviors[tankID]
	behaviorMu.RUnlock()
	if ok && factory != nil {
		return factory()
	}
	return &DefaultBehavior{}
}

// NewNPCBehavior returns a fresh ActorBehavior for a Mob/Boss template ID.
func NewNPCBehavior(npcTemplateID uint32) ActorBehavior {
	behaviorMu.RLock()
	factory, ok := npcBehaviors[npcTemplateID]
	behaviorMu.RUnlock()
	if ok && factory != nil {
		return factory()
	}
	return &DefaultBehavior{}
}

// DefaultBehavior implements standard ranged projectile (slot 0) and skill cast (slot 1..3).
type DefaultBehavior struct{}

func (b *DefaultBehavior) OnSpawn(ctx *ActorContext) {}

func (b *DefaultBehavior) OnUseSkill(ctx *ActorContext, slotNo uint8, targetID uint32, destX, destY int16) ActionResult {
	if ctx == nil || ctx.Config == nil {
		return ActionResult{}
	}
	template, speed := ctx.Config.SkillForSlot(slotNo)
	if slotNo == 0 {
		if ctx.Config.NormalBullet.Range > 0 {
			destX, destY = ProjectDest(ctx.PosX, ctx.PosY, destX, destY, ctx.Config.NormalBullet.Range)
		}
		dmgMult := GetEffectAddVal(template, 1.0)
		fireCD := uint32(ctx.Config.FireRateMS)
		if fireCD == 0 {
			fireCD = 500
		}
		return ActionResult{
			Fires: []FireEvent{
				{
					Template:   template,
					StartX:     ctx.PosX,
					StartY:     ctx.PosY,
					DestX:      destX,
					DestY:      destY,
					Speed:      speed,
					DamageMult: dmgMult,
				},
			},
			Cooldowns: []CooldownEvent{
				{SlotNo: 0, SkillID: template, CooldownMS: fireCD},
			},
		}
	}

	idx := int(slotNo - 1)
	if slotNo == 3 || slotNo == 10 {
		idx = 3
	}
	var cd uint32 = 5000
	// Fallback multipliers only when EffectTemplate has no fAddVal for this skill ID
	defaultMults := [4]float64{1.5, 2.5, 1.0, 2.0}
	var dmgMult float64
	if idx >= 0 && idx < 4 {
		dmgMult = GetEffectAddVal(template, defaultMults[idx])
		if r := int16(ctx.Config.Skills[idx].Range); r > 0 {
			destX, destY = ClampDest(ctx.PosX, ctx.PosY, destX, destY, r)
		}
		if ctx.Config.Skills[idx].CooldownMS > 0 {
			cd = ctx.Config.Skills[idx].CooldownMS
		}
		if ctx.Config.Skills[idx].DamageMult > 0 {
			dmgMult = ctx.Config.Skills[idx].DamageMult
		}
	} else {
		dmgMult = GetEffectAddVal(template, 1.5)
	}
	// Use SkillEvent for visual cast + FireEvent for the projectile (with damage multiplier)
	return ActionResult{
		Skills: []SkillEvent{
			{
				Template: template,
				TargetID: targetID,
				StartX:   ctx.PosX,
				StartY:   ctx.PosY,
				DestX:    destX,
				DestY:    destY,
			},
		},
		Fires: []FireEvent{
			{
				Template:   template,
				StartX:     ctx.PosX,
				StartY:     ctx.PosY,
				DestX:      destX,
				DestY:      destY,
				Speed:      speed,
				DamageMult: dmgMult,
			},
		},
		Cooldowns: []CooldownEvent{
			{SlotNo: slotNo, SkillID: template, CooldownMS: cd},
		},
	}
}

func (b *DefaultBehavior) OnBulletHit(ctx *ActorContext, template uint32, targetID uint32) ActionResult {
	return ActionResult{}
}

func (b *DefaultBehavior) OnTakeDamage(ctx *ActorContext, attackerID uint32, damage int32, isSkill bool) ActionResult {
	return ActionResult{}
}

func (b *DefaultBehavior) OnTick(ctx *ActorContext, nowMs int64) ActionResult {
	return ActionResult{}
}

// ProjectDest projects (destX, destY) along the aim ray from (startX, startY) to exact distance targetRange.
// Used for standard straight-line projectiles (matching BangBang_Offline TankActions.shoot).
func ProjectDest(startX, startY, destX, destY, targetRange int16) (int16, int16) {
	if targetRange == 0 {
		return destX, destY
	}
	dx := float64(destX - startX)
	dy := float64(destY - startY)
	dist := math.Hypot(dx, dy)
	if dist == 0 {
		return startX + targetRange, startY
	}
	scale := float64(targetRange) / dist
	return startX + int16(math.Round(dx*scale)), startY + int16(math.Round(dy*scale))
}

// ClampDest clamps (destX, destY) to at most maxRange distance from (startX, startY).
func ClampDest(startX, startY, destX, destY, maxRange int16) (int16, int16) {
	if maxRange <= 0 {
		return destX, destY
	}
	dx := float64(destX - startX)
	dy := float64(destY - startY)
	dist := math.Hypot(dx, dy)
	if dist <= float64(maxRange) {
		return destX, destY
	}
	if dist == 0 {
		return startX + maxRange, startY
	}
	scale := float64(maxRange) / dist
	return startX + int16(math.Round(dx*scale)), startY + int16(math.Round(dy*scale))
}

// ClampToArena keeps coordinates inside safe playable arena bounds.
func ClampToArena(x, y int16) (int16, int16) {
	if x < 40 {
		x = 40
	} else if x > 1560 {
		x = 1560
	}
	if y < 40 {
		y = 40
	} else if y > 920 {
		y = 920
	}
	return x, y
}
