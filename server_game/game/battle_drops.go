package game

import (
	"math"
	"math/rand"
)

// MapDrop represents a pickupable item/buff box on the map.
type MapDrop struct {
	ID       uint32
	Template uint32
	X        int16
	Y        int16
}

// AddDropEvent notifies clients (msg 1556) that a drop spawned on the map.
type AddDropEvent struct {
	DropID     uint32
	TemplateID uint32
	X          int16
	Y          int16
}

// PickupTemplates matches map_objects.py PICKUPS.
var PickupTemplates = []uint32{105, 106, 412, 413, 414, 417, 418}

func (bs *BattleState) nextDropIDLocked() uint32 {
	bs.NextDropID++
	return (4 << 24) | bs.NextDropID
}

// SpawnDropAtLocked rolls a drop at (x, y) with the given probability (0.0-1.0).
func (bs *BattleState) SpawnDropAtLocked(x, y int16, chance float64, result *TickResult) {
	if chance < 1.0 && rand.Float64() >= chance {
		return
	}
	if bs.Drops == nil {
		bs.Drops = make(map[uint32]*MapDrop)
	}
	tpl := PickupTemplates[rand.Intn(len(PickupTemplates))]
	id := bs.nextDropIDLocked()
	bs.Drops[id] = &MapDrop{ID: id, Template: tpl, X: x, Y: y}
	result.AddDrops = append(result.AddDrops, AddDropEvent{
		DropID:     id,
		TemplateID: tpl,
		X:          x,
		Y:          y,
	})
}

func (bs *BattleState) applyDropBuffLocked(targetID, tplID uint32, durMS int32, now int64, result *TickResult) {
	s := bs.States[targetID]
	if s == nil {
		return
	}
	if s.ActiveBuffs == nil {
		s.ActiveBuffs = make(map[uint32]ActiveBuff)
	}
	tpl, hasTpl := GetBuffTemplate(tplID)
	var expiresAt int64
	if durMS > 0 {
		expiresAt = now + int64(durMS)
	} else if durMS == 0 && hasTpl && tpl.PersistTime > 0 {
		expiresAt = now + int64(tpl.PersistTime)
		durMS = tpl.PersistTime
	}
	s.ActiveBuffs[tplID] = ActiveBuff{
		TemplateID:     tplID,
		InstID:         tplID,
		CasterID:       targetID,
		EffectType:     tpl.EffectType,
		TypeParam:      tpl.TypeParam,
		ValType:        tpl.ValType,
		EffectValA:     tpl.EffectValA,
		EffectValB:     tpl.EffectValB,
		TimeEffectValA: tpl.TimeEffectValA,
		StackAdd:       tpl.StackAdd,
		Stacks:         1,
		MaxStacks:      1,
		CoolTime:       tpl.CoolTime,
		Aspect:         tpl.Aspect,
		StartedAt:      now,
		ExpiresAt:      expiresAt,
	}
	var wireDur uint32
	if durMS > 0 {
		wireDur = uint32(durMS)
	} else {
		wireDur = 0xFFFFFFFF
	}
	result.Buffs = append(result.Buffs, BuffEvent{
		TargetID:   targetID,
		TemplateID: tplID,
		InstID:     tplID,
		Stacks:     1,
		DurationMS: wireDur,
	})
}

func (bs *BattleState) removeDropBuffLocked(targetID, tplID uint32, result *TickResult) {
	s := bs.States[targetID]
	if s == nil || s.ActiveBuffs == nil {
		return
	}
	if _, ok := s.ActiveBuffs[tplID]; ok {
		delete(s.ActiveBuffs, tplID)
		result.Buffs = append(result.Buffs, BuffEvent{
			Remove:   true,
			TargetID: targetID,
			InstID:   tplID,
		})
	}
}

// tickDrops handles periodic air-drops (every 60s) and pickup collection (48px radius).
func (bs *BattleState) tickDrops(positions map[uint32]*MemberPos, now int64, result *TickResult) {
	if len(bs.AirDrops) > 0 {
		if bs.AirDropDueAt == 0 {
			bs.AirDropDueAt = bs.StartTime + 60000
		}
		if now >= bs.AirDropDueAt {
			pt := bs.AirDrops[rand.Intn(len(bs.AirDrops))]
			bs.SpawnDropAtLocked(pt.X, pt.Y, 1.0, result)
			bs.AirDropDueAt += 60000
		}
	}

	if len(bs.Drops) == 0 {
		return
	}

	for dropID, drop := range bs.Drops {
		for memberID, state := range bs.States {
			if !state.Alive {
				continue
			}
			pos := positions[memberID]
			if pos == nil {
				continue
			}
			if math.Hypot(float64(pos.X-drop.X), float64(pos.Y-drop.Y)) > 48.0 {
				continue
			}

			picked := true
			switch drop.Template {
			case 412: // Heal 10% MaxHP
				if state.HP >= state.MaxHP {
					picked = false
				} else {
					heal := int32(math.Round(float64(state.MaxHP) * 0.10))
					if heal < 1 {
						heal = 1
					}
					before := state.HP
					state.HP += heal
					if state.HP > state.MaxHP {
						state.HP = state.MaxHP
					}
					delta := state.HP - before
					if delta > 0 {
						result.HpChanges = append(result.HpChanges, HpChangeEvent{ObjID: memberID, HP: state.HP})
						result.HpDeltas = append(result.HpDeltas, HpDeltaEvent{ObjID: memberID, Delta: delta, CasterID: memberID})
					}
				}
			case 413: // 3-hit Shield (buff 30101)
				state.MapShieldHits = 3
				bs.applyDropBuffLocked(memberID, 30101, -1, now, result)
			case 414: // Triple buff (30102, 30108, 30109)
				bs.applyDropBuffLocked(memberID, 30102, -1, now, result)
				bs.applyDropBuffLocked(memberID, 30108, -1, now, result)
				bs.applyDropBuffLocked(memberID, 30109, -1, now, result)
			case 417: // Speed boost 10s (30105)
				bs.applyDropBuffLocked(memberID, 30105, 10000, now, result)
			case 418: // Damage/Speed boost 30s (30106)
				bs.applyDropBuffLocked(memberID, 30106, 30000, now, result)
			case 105: // Triple spread ammo (15 shots, buff 203)
				bs.removeDropBuffLocked(memberID, 204, result)
				state.MapAmmoTemplate = 105
				state.MapAmmoRemaining = 15
				bs.applyDropBuffLocked(memberID, 203, -1, now, result)
			case 106: // Rapid burst ammo (15 shots, buff 204)
				bs.removeDropBuffLocked(memberID, 203, result)
				state.MapAmmoTemplate = 106
				state.MapAmmoRemaining = 15
				bs.applyDropBuffLocked(memberID, 204, -1, now, result)
			default:
				picked = false
			}

			if picked {
				delete(bs.Drops, dropID)
				result.RemovedObjects = append(result.RemovedObjects, dropID)
				break
			}
		}
	}
}

// ConsumeMapAmmoShot enhances a basic attack with pickup ammo (105 spread / 106 burst).
func (bs *BattleState) ConsumeMapAmmoShot(charID uint32, base FireEvent) ([]FireEvent, []BuffEvent) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok || !s.Alive || s.MapAmmoRemaining <= 0 {
		return nil, nil
	}
	tpl := s.MapAmmoTemplate
	s.MapAmmoRemaining--

	var extraFires []FireEvent
	dx := float64(base.DestX - base.StartX)
	dy := float64(base.DestY - base.StartY)
	dist := math.Hypot(dx, dy)
	baseAngle := math.Atan2(dy, dx)

	for _, i := range []int{-1, 1} {
		extra := base
		if tpl == 105 && dist > 0 {
			// ±15° spread
			ang := baseAngle + float64(i)*(15.0*math.Pi/180.0)
			extra.DestX = base.StartX + int16(math.Round(dist*math.Cos(ang)))
			extra.DestY = base.StartY + int16(math.Round(dist*math.Sin(ang)))
		}
		extraFires = append(extraFires, extra)
	}

	var removeBuffs []BuffEvent
	if s.MapAmmoRemaining <= 0 {
		s.MapAmmoTemplate = 0
		buffID := uint32(203)
		if tpl == 106 {
			buffID = 204
		}
		if s.ActiveBuffs != nil {
			delete(s.ActiveBuffs, buffID)
		}
		removeBuffs = append(removeBuffs, BuffEvent{
			Remove:   true,
			TargetID: charID,
			InstID:   buffID,
		})
	}
	return extraFires, removeBuffs
}
