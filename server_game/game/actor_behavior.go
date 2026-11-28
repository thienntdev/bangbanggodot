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
	Bounds  ArenaBounds
}

// ArenaBounds defines playable arena boundaries for tank movement and skill clamping.
type ArenaBounds struct {
	Left   int16
	Top    int16
	Right  int16
	Bottom int16
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
// Uses dynamic bounds from map data (matches Python clamp_tank_position).
func ClampToArena(x, y int16, b ArenaBounds) (int16, int16) {
	if x < b.Left {
		x = b.Left
	} else if x > b.Right {
		x = b.Right
	}
	if y < b.Top {
		y = b.Top
	} else if y > b.Bottom {
		y = b.Bottom
	}
	return x, y
}

// Aimed computes the destination point along the ray from (startX, startY) towards (destX, destY).
// If fixed is true, the travel distance is exactly distance (like dash/fixed-range skills).
// If fixed is false, the travel distance is min(actualDistance, distance) (like blink skills).
// Matches Python melee_common.aimed.
func Aimed(startX, startY, destX, destY int16, distance int16, fixed bool) (int16, int16) {
	dx := float64(destX - startX)
	dy := float64(destY - startY)
	length := math.Hypot(dx, dy)
	if length == 0 {
		return startX, startY
	}
	var frac float64
	if fixed {
		frac = float64(distance) / length
	} else {
		frac = math.Min(1.0, float64(distance)/length)
	}
	return startX + int16(math.Round(dx*frac)), startY + int16(math.Round(dy*frac))
}

const TankMoveHalf = 36.0

// RectContactSingle computes the swept collision fraction t in [0, 1] of a moving point (x1,y1)->(x2,y2)
// against an axis-aligned rectangle padded by padding on all sides.
// Matches Python combat_geometry.rect_contact.
func RectContactSingle(w WallRect, x1, y1, x2, y2, padding float64) (bool, float64) {
	dx := x2 - x1
	dy := y2 - y1
	low, high := 0.0, 1.0

	pLeft := w.Left - padding
	pRight := w.Right + padding
	pTop := w.Top - padding
	pBottom := w.Bottom + padding

	if dx == 0 {
		if x1 < pLeft || x1 > pRight {
			return false, 1.0
		}
	} else {
		t1 := (pLeft - x1) / dx
		t2 := (pRight - x1) / dx
		if t1 > t2 {
			t1, t2 = t2, t1
		}
		if t1 > low {
			low = t1
		}
		if t2 < high {
			high = t2
		}
		if low > high {
			return false, 1.0
		}
	}

	if dy == 0 {
		if y1 < pTop || y1 > pBottom {
			return false, 1.0
		}
	} else {
		t1 := (pTop - y1) / dy
		t2 := (pBottom - y1) / dy
		if t1 > t2 {
			t1, t2 = t2, t1
		}
		if t1 > low {
			low = t1
		}
		if t2 < high {
			high = t2
		}
		if low > high {
			return false, 1.0
		}
	}

	return true, low
}

// ClearTankLanding calculates the legal landing position for dashes and blinks (e.g. Wukong E, Space, Gundam R recoil).
// Matches Python combat_geometry.clear_tank_landing & battle_map.py.
// Tanks CAN cross inner walls, provided their 72px body (36px half-width) can legally land on open ground.
// If the destination overlaps a wall, it backtracks along the ray to the wall's front edge.
func ClearTankLanding(walls []WallRect, startX, startY, destX, destY int16, bounds ArenaBounds) (int16, int16) {
	destX, destY = ClampToArena(destX, destY, bounds)
	curX := float64(destX)
	curY := float64(destY)
	sX := float64(startX)
	sY := float64(startY)

	if len(walls) == 0 {
		return destX, destY
	}

	maxIter := len(walls) + 2
	if maxIter > 32 {
		maxIter = 32
	}

	for iter := 0; iter < maxIter; iter++ {
		var blocked []WallRect
		for _, w := range walls {
			pLeft := w.Left - (TankMoveHalf - 0.001)
			pRight := w.Right + (TankMoveHalf - 0.001)
			pTop := w.Top - (TankMoveHalf - 0.001)
			pBottom := w.Bottom + (TankMoveHalf - 0.001)
			if curX >= pLeft && curX <= pRight && curY >= pTop && curY <= pBottom {
				blocked = append(blocked, w)
			}
		}

		if len(blocked) == 0 {
			return int16(math.Round(curX)), int16(math.Round(curY))
		}

		minFrac := 2.0
		hitAny := false
		for _, w := range blocked {
			hit, frac := RectContactSingle(w, sX, sY, curX, curY, TankMoveHalf)
			if hit && frac >= 0 {
				hitAny = true
				if frac < minFrac {
					minFrac = frac
				}
			}
		}

		if !hitAny || minFrac <= 0 {
			return startX, startY
		}

		edgeX := sX + (curX-sX)*minFrac
		edgeY := sY + (curY-sY)*minFrac

		if curX > sX {
			curX = math.Floor(edgeX)
		} else if curX < sX {
			curX = math.Ceil(edgeX)
		} else {
			curX = math.Round(edgeX)
		}

		if curY > sY {
			curY = math.Floor(edgeY)
		} else if curY < sY {
			curY = math.Ceil(edgeY)
		} else {
			curY = math.Round(edgeY)
		}
	}

	return startX, startY
}
