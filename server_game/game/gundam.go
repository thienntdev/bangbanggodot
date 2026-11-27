package game

import (
	"math"
	"math/rand"
	"time"
)

func init() {
	RegisterTankBehavior(10000019, func() ActorBehavior {
		return &GundamBehavior{}
	})
}

// GundamBehavior implements custom combat logic for Tank 10000019 (Gundam).
// Reference: BangBang_Offline/server/gundam_actions.py
type GundamBehavior struct {
	DefaultBehavior
	comboTarget uint32
	comboCount  int
	comboUntil  int64
	readyUntil  int64
}

func (g *GundamBehavior) OnSpawn(ctx *ActorContext) {
	g.comboTarget = 0
	g.comboCount = 0
	g.comboUntil = 0
	g.readyUntil = 0
}

func (g *GundamBehavior) OnUseSkill(ctx *ActorContext, slotNo uint8, targetID uint32, destX, destY int16) ActionResult {
	if time.Now().UnixMilli() < g.readyUntil {
		return ActionResult{} // locked while charging Space laser
	}
	switch slotNo {
	case 0:
		// Basic attack: fast blue laser (302600, speed 1200, range 650)
		return g.DefaultBehavior.OnUseSkill(ctx, 0, targetID, destX, destY)

	case 1:
		// E (302701): Lock-on missile volley (requires targetID; 3 delayed homing missiles)
		// Python: power * D(self.effects[302701]['fAddVal']) per missile, school='energy'
		if targetID == 0 {
			return ActionResult{}
		}
		startX, startY := ctx.PosX, ctx.PosY
		missileDestX, missileDestY := destX, destY
		missileMult := GetEffectAddVal(302701, 0.90)
		var cd uint32 = 6000
		if st, ok := GetSkillTemplate(302701); ok && st.CoolTime > 0 {
			cd = st.CoolTime
		}
		delayed := make([]DelayedAction, 0, 3)
		for i := 1; i <= 3; i++ {
			delayed = append(delayed, DelayedAction{
				DelayMS: i * 150,
				Run: func() ActionResult {
					return ActionResult{
						Fires: []FireEvent{
							{
								Template:   302701,
								StartX:     startX,
								StartY:     startY,
								DestX:      missileDestX,
								DestY:      missileDestY,
								Speed:      900,
								DamageMult: missileMult,
								School:     "energy",
								Basic:      true,
								TargetID:   targetID,
							},
						},
					}
				},
			})
		}
		return ActionResult{
			Skills: []SkillEvent{
				{
					Template: 302701,
					TargetID: targetID,
					StartX:   startX,
					StartY:   startY,
					DestX:    destX,
					DestY:    destY,
				},
			},
			Cooldowns: []CooldownEvent{
				{SlotNo: 1, SkillID: 302701, CooldownMS: cd},
			},
			Delayed: delayed,
		}

	case 2:
		// Space (302801): Windup (ready=1, stop move) -> ReadyTime later fire laser beam (ready=0)
		// Python: power * D(self.effects[302801]['fAddVal']), school='energy', beam/rect area
		startX, startY := ctx.PosX, ctx.PosY
		beamLen := int16(528)
		beamMult := GetEffectAddVal(302801, 4.45)
		if eff, ok := GetEffectTemplate(302801); ok && eff.Range1 > 0 {
			beamLen = int16(eff.Range1)
		}
		var cd uint32 = 25000
		readyMS := 500
		if st, ok := GetSkillTemplate(302801); ok {
			if st.CoolTime > 0 {
				cd = st.CoolTime
			}
			if st.ReadyTime > 0 {
				readyMS = int(st.ReadyTime)
			}
		}
		beamDestX, beamDestY := ProjectDest(startX, startY, destX, destY, beamLen)
		g.readyUntil = time.Now().UnixMilli() + int64(readyMS)
		return ActionResult{
			Moves: []MoveEvent{
				{DestX: startX, DestY: startY, Speed: 0, MoveType: 5},
			},
			Skills: []SkillEvent{
				{
					Template: 302801,
					StartX:   startX,
					StartY:   startY,
					DestX:    beamDestX,
					DestY:    beamDestY,
					Ready:    1,
				},
			},
			Cooldowns: []CooldownEvent{
				{SlotNo: 2, SkillID: 302801, CooldownMS: cd},
			},
			Delayed: []DelayedAction{
				{
					DelayMS: readyMS,
					Run: func() ActionResult {
						return ActionResult{
							Skills: []SkillEvent{
								{
									Template: 302801,
									StartX:   startX,
									StartY:   startY,
									DestX:    beamDestX,
									DestY:    beamDestY,
									Ready:    0,
								},
							},
							// Beam sweeps a 528x72 rectangle (Python: gundam_actions.py)
							AreaHits: []AreaHitEvent{
								{
									Shape:      "rect",
									Template:   302801,
									StartX:     startX,
									StartY:     startY,
									DestX:      beamDestX,
									DestY:      beamDestY,
									Radius:     float64(beamLen),
									HalfWidth:  36,
									School:     "energy",
									DamageMult: beamMult,
								},
							},
						}
					},
				},
			},
		}

	case 3, 10:
		// R (302901): Fires 302911 projectile forward + recoil dash backward (speed 960)
		// Python: power * D(self.effects[302911]['fAddVal']), school='energy'
		shotRange := int16(552)
		var cd uint32 = 8000
		if st, ok := GetSkillTemplate(302901); ok {
			if st.CoolTime > 0 {
				cd = st.CoolTime
			}
			if st.Range > 0 && st.Range < 30000 {
				shotRange = int16(st.Range)
			}
		}
		recoilDist := int16(300)
		if eff, ok := GetEffectTemplate(302902); ok && eff.EffectValB > 0 {
			recoilDist = int16(eff.EffectValB)
		}
		rMult := GetEffectAddVal(302911, 1.22)
		shotDestX, shotDestY := ProjectDest(ctx.PosX, ctx.PosY, destX, destY, shotRange)
		recoilX, recoilY := ProjectDest(ctx.PosX, ctx.PosY, destX, destY, -recoilDist)
		recoilX, recoilY = ClampToArena(recoilX, recoilY)
		if len(ctx.Walls) > 0 {
			if hit, frac := SegmentHitsWall(ctx.Walls, float64(ctx.PosX), float64(ctx.PosY), float64(recoilX), float64(recoilY)); hit {
				safeFrac := math.Max(0, frac-0.05)
				recoilX = ctx.PosX + int16(math.Round(float64(recoilX-ctx.PosX)*safeFrac))
				recoilY = ctx.PosY + int16(math.Round(float64(recoilY-ctx.PosY)*safeFrac))
			}
		}
		return ActionResult{
			Fires: []FireEvent{
				{
					Template:   302911,
					StartX:     ctx.PosX,
					StartY:     ctx.PosY,
					DestX:      shotDestX,
					DestY:      shotDestY,
					Speed:      800,
					DamageMult: rMult,
					School:     "energy",
					Basic:      true,
				},
			},
			Moves: []MoveEvent{
				{DestX: recoilX, DestY: recoilY, Speed: 960, MoveType: 3},
			},
			Cooldowns: []CooldownEvent{
				{SlotNo: 10, SkillID: 302901, CooldownMS: cd},
			},
		}

	default:
		return g.DefaultBehavior.OnUseSkill(ctx, slotNo, targetID, destX, destY)
	}
}

func (g *GundamBehavior) OnBulletHit(ctx *ActorContext, template uint32, targetID uint32) ActionResult {
	var res ActionResult
	if template == 302911 {
		// R active: 50% slow for 2s
		res.Buffs = append(res.Buffs, BuffEvent{
			TargetID: targetID, TemplateID: 302912, InstID: 302912, Stacks: 1, DurationMS: 2000,
		})
	}
	// Primary attacks (Basic 302600, E 302701, R 302911) build 3-hit mark; extra missile 302602 does not recurse
	if template != 302600 && template != 302701 && template != 302911 {
		return res
	}
	now := time.Now().UnixMilli()
	if g.comboTarget != targetID || now >= g.comboUntil {
		g.comboCount = 0
	}
	g.comboTarget = targetID
	g.comboCount++
	g.comboUntil = now + 1000 // BuffTemplate 302601 iPersistTime = 1000ms

	// Clear previous mark rings (302601, 302602)
	res.Buffs = append(res.Buffs,
		BuffEvent{Remove: true, TargetID: targetID, InstID: 302601},
		BuffEvent{Remove: true, TargetID: targetID, InstID: 302602},
	)
	if g.comboCount >= 3 {
		g.comboCount = 0
		res.Buffs = append(res.Buffs, BuffEvent{
			TargetID: targetID, TemplateID: 302612, InstID: 302612, Stacks: 1, DurationMS: 500,
		})
		res.AreaHits = append(res.AreaHits, AreaHitEvent{
			Shape:      "circle",
			Template:   302611,
			StartX:     ctx.TargetX,
			StartY:     ctx.TargetY,
			DestX:      ctx.TargetX,
			DestY:      ctx.TargetY,
			Radius:     40,
			School:     "energy",
			DamageMult: GetEffectAddVal(302611, 1.5),
			Basic:      true,
		})
	} else {
		markID := uint32(302600 + g.comboCount) // 302601 or 302602
		res.Buffs = append(res.Buffs, BuffEvent{
			TargetID: targetID, TemplateID: markID, InstID: markID, Stacks: 1, DurationMS: 1000,
		})
	}

	// 25% chance to fire an extra homing missile (302602)
	if rand.Float64() < 0.25 {
		res.Fires = append(res.Fires, FireEvent{
			Template:   302602,
			StartX:     ctx.PosX,
			StartY:     ctx.PosY,
			DestX:      ctx.TargetX,
			DestY:      ctx.TargetY,
			Speed:      900,
			DamageMult: GetEffectAddVal(302701, 0.90),
			School:     "energy",
			Basic:      true,
			TargetID:   targetID,
		})
	}
	return res
}
