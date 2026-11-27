package game

import "math"

// TurretFireEvent represents a projectile fired by a map turret (iType == 4).
type TurretFireEvent struct {
	BulletID  uint32
	ShooterID uint32
	StartX    int16
	StartY    int16
	DestX     int16
	DestY     int16
	Speed     int16
	Template  uint32
}

func (bs *BattleState) nextBulletIDLocked() uint32 {
	bs.NextBulletID++
	return 0x50000000 | bs.NextBulletID
}

// tickTurrets runs AI targeting and firing for alive map turrets (iType == 4).
func (bs *BattleState) tickTurrets(positions map[uint32]*MemberPos, now int64, result *TickResult) {
	for _, npc := range bs.NPCs {
		if !npc.Alive || npc.Type != 4 || now < npc.TurretNextShotAt {
			continue
		}
		var bestID uint32
		var bestPos *MemberPos
		bestDist := math.MaxFloat64

		for memberID, state := range bs.States {
			if !state.Alive || state.Camp == npc.Camp || (state.Camp != 1 && state.Camp != 2) {
				continue
			}
			if now < state.DamageImmuneUntil {
				continue
			}
			pos := positions[memberID]
			if pos == nil {
				continue
			}
			dist := math.Hypot(float64(pos.X-npc.X), float64(pos.Y-npc.Y))
			if dist > 0 && dist <= float64(npc.AlertRange) && dist < bestDist {
				bestDist = dist
				bestID = memberID
				bestPos = pos
			}
		}
		if bestID == 0 || bestPos == nil {
			continue
		}

		if npc.TurretTargetID != bestID {
			npc.TurretTargetID = bestID
			npc.TurretHits = 0
		} else if npc.TurretHits < 5 {
			npc.TurretHits++
		}
		npc.TurretNextShotAt = now + int64(npc.FireIntervalMS)

		raw := float64(npc.Attack)
		school := "physical"
		if raw <= 0 && npc.EnergyAtk > 0 {
			raw = float64(npc.EnergyAtk)
			school = "energy"
		}
		if raw <= 0 {
			raw = 120
		}
		if npc.TurretHits >= 5 {
			raw *= 1.2
		}

		skillID := npc.TurretSkill
		if skillID == 0 {
			skillID = 301
		}
		speed := int16(700)
		lifeMS := int64(1000)
		if st, ok := GetSkillTemplate(skillID); ok {
			if st.LifeTime > 0 {
				lifeMS = int64(st.LifeTime)
				if st.FlyRange > 0 {
					if spd := int32(st.FlyRange) * 1000 / st.LifeTime; spd > 0 && spd < 30000 {
						speed = int16(spd)
					}
				}
			}
		}

		bulletID := bs.nextBulletIDLocked()
		var targetID uint32
		if skillID == 301 {
			targetID = bestID
		}
		bs.Bullets[bulletID] = &BulletFlight{
			ID:        bulletID,
			OwnerID:   npc.ID,
			Camp:      npc.Camp,
			Template:  skillID,
			StartX:    float64(npc.X),
			StartY:    float64(npc.Y),
			DestX:     float64(bestPos.X),
			DestY:     float64(bestPos.Y),
			Speed:     float64(speed),
			StartTime: now,
			LifeMS:    lifeMS,
			Power:     raw,
			School:    school,
			Basic:     true,
			TargetID:  targetID,
		}
		result.TurretFires = append(result.TurretFires, TurretFireEvent{
			BulletID:  bulletID,
			ShooterID: npc.ID,
			StartX:    npc.X,
			StartY:    npc.Y,
			DestX:     bestPos.X,
			DestY:     bestPos.Y,
			Speed:     speed,
			Template:  skillID,
		})
	}
}
