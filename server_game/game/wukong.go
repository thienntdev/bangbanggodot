package game

import (
	"time"
)

func init() {
	RegisterTankBehavior(10000036, func() ActorBehavior {
		return &WukongBehavior{}
	})
}

const (
	wukongBuffEmpower     uint32 = 310111
	wukongBuffEmpowerGlow uint32 = 310112
	wukongBuffVanish      uint32 = 310302
)

// WukongBehavior implements custom combat logic for Tank 10000036 (Wukong).
// Reference: BangBang_Offline/server/wukong_actions.py
type WukongBehavior struct {
	DefaultBehavior
	empowered      bool
	empoweredUntil int64
	lockedUntil    int64
	counterUntil   int64
}

func (w *WukongBehavior) OnSpawn(ctx *ActorContext) {
	w.empowered = false
	w.empoweredUntil = 0
	w.lockedUntil = 0
	w.counterUntil = 0
}

func (w *WukongBehavior) empower(actorID uint32) ([]BuffEvent, []SlotSwapEvent, []DelayedAction) {
	w.empowered = true
	expireAt := time.Now().UnixMilli() + 3000
	w.empoweredUntil = expireAt
	buffs := []BuffEvent{
		{TargetID: actorID, TemplateID: wukongBuffEmpower, InstID: 9001, Stacks: 1, DurationMS: 3000},
		{TargetID: actorID, TemplateID: wukongBuffEmpowerGlow, InstID: 9002, Stacks: 1, DurationMS: 3000},
	}
	swaps := []SlotSwapEvent{
		{SlotNo: 0, SkillID: 310121},
	}
	delayed := []DelayedAction{
		{
			DelayMS: 3000,
			Run: func() ActionResult {
				if !w.empowered {
					return ActionResult{} // already consumed by empowered attack
				}
				b, sw := w.consumeEmpower(actorID)
				return ActionResult{Buffs: b, SlotSwaps: sw}
			},
		},
	}
	return buffs, swaps, delayed
}

func (w *WukongBehavior) consumeEmpower(actorID uint32) ([]BuffEvent, []SlotSwapEvent) {
	w.empowered = false
	w.empoweredUntil = 0
	buffs := []BuffEvent{
		{Remove: true, TargetID: actorID, InstID: 9001},
		{Remove: true, TargetID: actorID, InstID: 9002},
	}
	swaps := []SlotSwapEvent{
		{SlotNo: 0, SkillID: 310100},
	}
	return buffs, swaps
}

func (w *WukongBehavior) OnUseSkill(ctx *ActorContext, slotNo uint8, targetID uint32, destX, destY int16) ActionResult {
	now := time.Now().UnixMilli()
	if now < w.lockedUntil {
		return ActionResult{} // locked during Space vanish or R windup
	}
	switch slotNo {
	case 0:
		// Empowered basic attack (310121): windup (ready=1) -> 10ms later sweep hit (ready=0) + clear empower
		if w.empowered && now < w.empoweredUntil {
			startX, startY := ctx.PosX, ctx.PosY
			sweepX, sweepY := ProjectDest(startX, startY, destX, destY, 192)
			buffs, swaps := w.consumeEmpower(ctx.ActorID)
			fireCD := uint32(500)
			if ctx.Config != nil && ctx.Config.FireRateMS > 0 {
				fireCD = uint32(ctx.Config.FireRateMS)
			}
			return ActionResult{
				Moves: []MoveEvent{
					{DestX: startX, DestY: startY, Speed: 0, MoveType: 5},
				},
				Skills: []SkillEvent{
					{
						Template: 310121,
						StartX:   startX,
						StartY:   startY,
						DestX:    sweepX,
						DestY:    sweepY,
						Ready:    1,
					},
				},
				Buffs:     buffs,
				SlotSwaps: swaps,
				Cooldowns: []CooldownEvent{
					{SlotNo: 0, SkillID: 310121, CooldownMS: fireCD},
				},
				Delayed: []DelayedAction{
					{
						DelayMS: 10,
						Run: func() ActionResult {
							return ActionResult{
								Skills: []SkillEvent{
									{
										Template: 310121,
										StartX:   startX,
										StartY:   startY,
										DestX:    sweepX,
										DestY:    sweepY,
										Ready:    0,
									},
								},
								AreaHits: []AreaHitEvent{
									{
										Shape:      "cone",
										Template:   310121,
										StartX:     startX,
										StartY:     startY,
										DestX:      sweepX,
										DestY:      sweepY,
										Radius:     192,
										AngleDeg:   180,
										School:     "physical",
										DamageMult: GetEffectAddVal(310121, 1.0),
										Basic:      true,
										ForceCrit:  true,
										Lifesteal:  0.25,
										OnHitBuffs: []uint32{310122, 310123},
									},
								},
							}
						},
					},
				},
			}
		}
		return w.DefaultBehavior.OnUseSkill(ctx, 0, targetID, destX, destY)

	case 1:
		// E (310201): Dash forward 384px at speed 960 + 50% dmg reduction (2s) + 1s counter-shield + empower
		intendedX, intendedY := Aimed(ctx.PosX, ctx.PosY, destX, destY, 384, true)
		dashX, dashY := ClearTankLanding(ctx.Walls, ctx.PosX, ctx.PosY, intendedX, intendedY, ctx.Bounds)
		buffs, swaps, expDelayed := w.empower(ctx.ActorID)
		buffs = append(buffs,
			BuffEvent{TargetID: ctx.ActorID, TemplateID: 310202, InstID: 310202, Stacks: 1, DurationMS: 2000},
			BuffEvent{TargetID: ctx.ActorID, TemplateID: 310203, InstID: 310203, Stacks: 1, DurationMS: 2000},
			BuffEvent{TargetID: ctx.ActorID, TemplateID: 310204, InstID: 310204, Stacks: 1, DurationMS: 1000},
			BuffEvent{TargetID: ctx.ActorID, TemplateID: 310211, InstID: 310211, Stacks: 1, DurationMS: 400},
		)
		w.counterUntil = now + 1000
		return ActionResult{
			Skills: []SkillEvent{
				{
					Template: 310201,
					StartX:   ctx.PosX,
					StartY:   ctx.PosY,
					DestX:    dashX,
					DestY:    dashY,
				},
			},
			Moves: []MoveEvent{
				{DestX: dashX, DestY: dashY, Speed: 960, MoveType: 3},
			},
			Buffs:           buffs,
			SlotSwaps:       swaps,
			Delayed:         expDelayed,
			DamageReducePct: 0.50,
			DamageReduceMS:  2000,
			Cooldowns: []CooldownEvent{
				{SlotNo: 1, SkillID: 310201, CooldownMS: 6000},
			},
		}

	case 2:
		// Space (310301): Blink up to 264px + vanish buff (310302, immune 700ms) + scene objects → 700ms later land & empower
		// Matches Python melee_common.aimed (fixed=false) & clear_tank_landing
		startX, startY := ctx.PosX, ctx.PosY
		intendedX, intendedY := Aimed(startX, startY, destX, destY, 264, false)
		blinkX, blinkY := ClearTankLanding(ctx.Walls, startX, startY, intendedX, intendedY, ctx.Bounds)
		actorID := ctx.ActorID
		camp := ctx.Camp
		w.lockedUntil = now + 700
		return ActionResult{
			ImmuneMS: 700,
			Moves: []MoveEvent{
				{DestX: blinkX, DestY: blinkY, Speed: 0, MoveType: 5},
			},
			Objects: []ObjectEvent{
				{Template: 310302, PosX: startX, PosY: startY, Camp: camp, OwnerID: actorID, LifeMS: 360},
				{Template: 310304, PosX: blinkX, PosY: blinkY, Camp: camp, OwnerID: actorID, LifeMS: 700},
				{Template: 310305, PosX: blinkX, PosY: blinkY, Camp: camp, OwnerID: actorID, LifeMS: 1350},
			},
			Buffs: []BuffEvent{
				{TargetID: actorID, TemplateID: wukongBuffVanish, InstID: 9003, Stacks: 1, DurationMS: 700},
			},
			Cooldowns: []CooldownEvent{
				{SlotNo: 2, SkillID: 310301, CooldownMS: 20000},
			},
			Delayed: []DelayedAction{
				{
					DelayMS: 700,
					Run: func() ActionResult {
						buffs, swaps, expDelayed := w.empower(actorID)
						buffs = append(buffs, BuffEvent{Remove: true, TargetID: actorID, InstID: 9003})
						return ActionResult{
							Skills: []SkillEvent{
								{
									Template: 310301,
									StartX:   blinkX,
									StartY:   blinkY,
									DestX:    blinkX,
									DestY:    blinkY,
									Ready:    0,
								},
							},
							AreaHits: []AreaHitEvent{
								{
									Shape:      "circle",
									Template:   310301,
									StartX:     blinkX,
									StartY:     blinkY,
									DestX:      blinkX,
									DestY:      blinkY,
									Radius:     192,
									School:     "physical",
									DamageMult: GetEffectAddVal(310311, 4.87),
									OnHitBuffs: []uint32{310312},
								},
							},
							Buffs:     buffs,
							SlotSwaps: swaps,
							Delayed:   expDelayed,
						}
					},
				},
			},
		}

	case 3, 10:
		// R (310401): Windup (ready=1, 100ms) -> 100ms later area slam (ready=0) & empower
		startX, startY := ctx.PosX, ctx.PosY
		actorID := ctx.ActorID
		w.lockedUntil = now + 100
		return ActionResult{
			Moves: []MoveEvent{
				{DestX: startX, DestY: startY, Speed: 0, MoveType: 5},
			},
			Skills: []SkillEvent{
				{
					Template: 310401,
					StartX:   startX,
					StartY:   startY,
					DestX:    destX,
					DestY:    destY,
					Ready:    1,
				},
			},
			Cooldowns: []CooldownEvent{
				{SlotNo: 10, SkillID: 310401, CooldownMS: 8000},
			},
			Delayed: []DelayedAction{
				{
					DelayMS: 100,
					Run: func() ActionResult {
						buffs, swaps, expDelayed := w.empower(actorID)
						return ActionResult{
							Skills: []SkillEvent{
								{
									Template: 310401,
									StartX:   startX,
									StartY:   startY,
									DestX:    destX,
									DestY:    destY,
									Ready:    0,
								},
							},
							AreaHits: []AreaHitEvent{
								{
									Shape:      "circle",
									Template:   310401,
									StartX:     startX,
									StartY:     startY,
									DestX:      startX,
									DestY:      startY,
									Radius:     216,
									School:     "physical",
									DamageMult: GetEffectAddVal(310401, 1.77),
									OnHitBuffs: []uint32{310402},
								},
							},
							Buffs:     buffs,
							SlotSwaps: swaps,
							Delayed:   expDelayed,
						}
					},
				},
			},
		}

	default:
		return w.DefaultBehavior.OnUseSkill(ctx, slotNo, targetID, destX, destY)
	}
}

func (w *WukongBehavior) OnTakeDamage(ctx *ActorContext, attackerID uint32, damage int32, isSkill bool) ActionResult {
	if !isSkill || damage <= 0 || time.Now().UnixMilli() >= w.counterUntil {
		return ActionResult{}
	}
	w.counterUntil = 0
	return ActionResult{
		Buffs: []BuffEvent{
			{Remove: true, TargetID: ctx.ActorID, InstID: 310204},
			{TargetID: ctx.ActorID, TemplateID: 310223, InstID: 310223, Stacks: 1, DurationMS: 2000},
		},
		Shields: []ShieldEvent{
			{TargetID: ctx.ActorID, MaxHPPct: 0.25},
		},
		CooldownPcts: []CooldownPctEvent{
			{SlotNo: 1, SkillID: 310201, Factor: 0.75},
			{SlotNo: 10, SkillID: 310401, Factor: 0.75},
		},
	}
}
