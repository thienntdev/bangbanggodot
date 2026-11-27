package game

import (
	"math"
	"math/rand"
)

func (bs *BattleState) ApplyAreaHit(ownerID uint32, ownerCamp uint8, ev AreaHitEvent, positions map[uint32]*MemberPos, now int64) (TickResult, []uint32) {
	bs.mu.Lock()
	defer bs.mu.Unlock()

	var result TickResult
	var hitPlayers []uint32
	if bs.Finished {
		return result, nil
	}

	attacker, hasAttacker := bs.States[ownerID]
	var power, pierce float64 = 100, 0
	if hasAttacker {
		if cfg := GetTankConfig(attacker.TankID); cfg != nil {
			if ev.School == "energy" {
				power = cfg.Combat.EnergyAtk
				pierce = cfg.Combat.EnergyPen
			} else {
				power = cfg.Combat.Attack
				pierce = cfg.Combat.Pierce
			}
		}
	}
	if power <= 0 {
		power = 100
	}
	mult := ev.DamageMult
	if mult <= 0 {
		mult = 1.0
	}
	raw := power * mult

	sx, sy := float64(ev.StartX), float64(ev.StartY)
	dxAim, dyAim := float64(ev.DestX)-sx, float64(ev.DestY)-sy
	aimDist := math.Hypot(dxAim, dyAim)
	ux, uy := 1.0, 0.0
	if aimDist > 0 {
		ux, uy = dxAim/aimDist, dyAim/aimDist
	}

	inShape := func(tx, ty float64) bool {
		dx, dy := tx-sx, ty-sy
		switch ev.Shape {
		case "cone":
			dist := math.Hypot(dx, dy)
			if dist > ev.Radius+HitboxRadius {
				return false
			}
			if dist == 0 {
				return true
			}
			dot := (dx*ux + dy*uy) / dist
			halfRad := (ev.AngleDeg * math.Pi / 180.0) / 2.0
			return dot >= math.Cos(halfRad)
		case "rect":
			along := dx*ux + dy*uy
			side := -dx*uy + dy*ux
			outX := math.Max(0, math.Max(-along, along-ev.Radius))
			outY := math.Max(0, math.Abs(side)-ev.HalfWidth)
			return math.Hypot(outX, outY) <= HitboxRadius
		default: // "circle"
			return math.Hypot(dx, dy) <= ev.Radius+HitboxRadius
		}
	}

	var totalLifesteal float64

	// 1. Check enemy players
	for memberID, state := range bs.States {
		if !state.Alive || state.Camp == ownerCamp || memberID == ownerID {
			continue
		}
		pos := positions[memberID]
		if pos == nil || !inShape(float64(pos.X), float64(pos.Y)) {
			continue
		}
		hitPlayers = append(hitPlayers, memberID)

		var targetArmor float64
		armorParam := AttrPhysArmor
		if ev.School == "energy" {
			armorParam = AttrEnergyArmor
		}
		if cfg := GetTankConfig(state.TankID); cfg != nil {
			if ev.School == "energy" {
				targetArmor = cfg.Combat.EnergyDef
			} else {
				targetArmor = cfg.Combat.Armor
			}
		}
		hitRaw := raw
		hitPierce := pierce
		if hasAttacker {
			atkParam := AttrPhysAtk
			pierceParam := AttrPhysPierce
			if ev.School == "energy" {
				atkParam = AttrEnergyAtk
				pierceParam = AttrEnergyPierce
			}
			hitRaw = hitRaw*(1+AttrBonusLocked(attacker, now, AttrAllAtk, atkParam)) + AttrFlatBonusLocked(attacker, now, AttrAllAtk, atkParam)
			hitPierce = hitPierce*(1+AttrBonusLocked(attacker, now, AttrAllPierce, pierceParam)) + AttrFlatBonusLocked(attacker, now, AttrAllPierce, pierceParam)
		}
		defBonusPct := AttrBonusLocked(state, now, AttrAllArmor, armorParam)
		defBonusFlat := AttrFlatBonusLocked(state, now, AttrAllArmor, armorParam)
		reductions, incomingBonus := DamageModifiersLocked(state, ev.Basic, now)
		isCrit := ev.ForceCrit || (ev.Basic && ev.School != "true" && rand.Float64() < 0.15)
		dmgF := CalculateDamage(DamageParams{
			Raw:           hitRaw,
			School:        ev.School,
			Pierce:        hitPierce,
			TargetArmor:   targetArmor,
			DefBonusPct:   defBonusPct,
			DefBonusFlat:  defBonusFlat,
			IncomingBonus: incomingBonus,
			Reductions:    reductions,
			Critical:      isCrit,
		})
		damage := int32(dmgF)
		if damage < 1 {
			damage = 1
		}
		var immune bool
		damage, immune = applyDefenseModifiers(state, damage, now)
		if immune {
			continue
		}
		result.TakeDamages = append(result.TakeDamages, TakeDamageEvent{
			TargetID:   memberID,
			AttackerID: ownerID,
			Damage:     damage,
			IsSkill:    !ev.Basic,
		})

		hpBefore := state.HP
		shieldAbsorbed := int32(0)
		if state.Shield > 0 {
			if state.Shield >= damage {
				state.Shield -= damage
				shieldAbsorbed = damage
				damage = 0
			} else {
				shieldAbsorbed = state.Shield
				damage -= state.Shield
				state.Shield = 0
			}
			result.ShieldChanges = append(result.ShieldChanges, ShieldChangeEvent{
				ObjID:  memberID,
				Shield: state.Shield,
			})
		}

		state.HP -= damage
		if state.HP < 0 {
			state.HP = 0
		}
		hpLoss := hpBefore - state.HP
		if hasAttacker {
			attacker.DamageOut += shieldAbsorbed + hpLoss
		}
		if ev.Lifesteal > 0 && hpLoss > 0 {
			totalLifesteal += float64(hpLoss) * ev.Lifesteal
		}

		result.HpChanges = append(result.HpChanges, HpChangeEvent{
			ObjID: memberID,
			HP:    state.HP,
		})
		hpDelta := state.HP - hpBefore
		if hpDelta != 0 || shieldAbsorbed > 0 {
			delta := hpDelta
			if shieldAbsorbed > 0 && delta == 0 {
				delta = -shieldAbsorbed
			}
			result.HpDeltas = append(result.HpDeltas, HpDeltaEvent{
				ObjID:    memberID,
				Delta:    delta,
				Crit:     isCrit,
				CasterID: ownerID,
			})
		}

		if state.HP <= 0 {
			state.Alive = false
			state.Deaths++
			elapsed := now - bs.StartTime
			state.RespawnAt = now + RespawnDelay(elapsed)
			ClearBuffsOnDeathLocked(state, memberID, &result)

			var killerCamp uint8
			if hasAttacker {
				attacker.Kills++
				killerCamp = attacker.Camp
				if bs.ModeType != 1 && bs.ModeType != 2 {
					bs.Scores[killerCamp]++
				}
			}
			result.Deaths = append(result.Deaths, DeathEvent{
				VictimID: memberID,
				KillerID: ownerID,
				SkillTpl: ev.Template,
				X:        pos.X,
				Y:        pos.Y,
			})
			winTarget := bs.WinTarget
			if winTarget <= 0 {
				winTarget = WinKills
			}
			if killerCamp != 0 && bs.ModeType != 1 && bs.ModeType != 2 && bs.Scores[killerCamp] >= winTarget {
				bs.Finished = true
				bs.Winner = killerCamp
				result.GameOver = true
				result.Winner = killerCamp
				result.Scores = bs.Scores
				result.ElapsedMS = int32(now - bs.StartTime)
			}
		}
	}

	// 2. Check destructible NPCs
	for npcID, npc := range bs.NPCs {
		if !npc.Alive || npc.Camp == ownerCamp {
			continue
		}
		if !inShape(float64(npc.X), float64(npc.Y)) {
			continue
		}
		var npcDmg int32
		if npc.Type == 3 || npc.Type == 4 || npc.Type == 6 {
			npcDmg = int32(raw)
		} else {
			npcDmg = npc.MaxHP / 4
		}
		if npcDmg < 1 {
			npcDmg = 1
		}
		npc.HP -= npcDmg
		if npc.HP < 0 {
			npc.HP = 0
		}
		result.NPCDamages = append(result.NPCDamages, NPCDamageEvent{
			NpcID: npcID,
			HP:    npc.HP,
			Dead:  npc.HP <= 0,
			X:     npc.X,
			Y:     npc.Y,
		})
		if npc.HP <= 0 {
			npc.Alive = false
			if npc.Type == 6 && npc.RepairTarget != 0 {
				result.Buffs = append(result.Buffs, BuffEvent{
					Remove: true, TargetID: npc.RepairTarget, InstID: 10,
				})
				npc.RepairTarget = 0
				npc.RepairTicksLeft = 0
			}
			if npc.Type == 3 && (npc.Camp == 1 || npc.Camp == 2) {
				winner := uint8(3 - npc.Camp)
				bs.Finished = true
				bs.Winner = winner
				result.GameOver = true
				result.Winner = winner
				result.Scores = bs.Scores
				result.ElapsedMS = int32(now - bs.StartTime)
			}
		}
	}

	// 3. Apply lifesteal heal to attacker
	if hasAttacker && attacker.Alive && totalLifesteal >= 1 {
		heal := int32(math.Round(totalLifesteal))
		hpBefore := attacker.HP
		attacker.HP += heal
		if attacker.HP > attacker.MaxHP {
			attacker.HP = attacker.MaxHP
		}
		actualHeal := attacker.HP - hpBefore
		if actualHeal > 0 {
			result.HpChanges = append(result.HpChanges, HpChangeEvent{
				ObjID: ownerID,
				HP:    attacker.HP,
			})
			result.HpDeltas = append(result.HpDeltas, HpDeltaEvent{
				ObjID:    ownerID,
				Delta:    actualHeal,
				Crit:     false,
				CasterID: ownerID,
			})
		}
	}

	return result, hitPlayers
}

// tickFlags updates capture progress and periodic occupy scoring (occupy_rules.py).
