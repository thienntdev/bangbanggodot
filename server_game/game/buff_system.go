package game

import "math"

// Buff/debuff EffectType constants matching BuffTemplate_table.xml and battle_runtime.py.
const (
	BuffEffectIncomingAmp int32 = 2   // Debuff: incoming damage amplification (+%)
	BuffEffectPeriodic    int32 = 27  // Periodic DoT (<0) or HoT (>0) every CoolTime ms
	BuffEffectDmgReduce   int32 = 29  // Damage reduction (%)
	BuffEffectStun        int32 = 30  // Stun / Knockup / Freeze (cannot move, attack, or cast)
	BuffEffectSilence     int32 = 31  // Silence (cannot cast skills)
	BuffEffectBanSkills   int32 = 35  // Silence excluding basic attack (masked by EffectValB)
	BuffEffectRoot        int32 = 36  // Root / Snare (cannot move, can attack/cast)
	BuffEffectConfuse     int32 = 39  // Confuse / Disorient (client-side reverse controls)
	BuffEffectUnstoppable int32 = 54  // Unstoppable / CC immunity against harmful hard CC
	BuffEffectBanActions  int32 = 66  // Ban actions including basic attack (masked by EffectValB)
	BuffEffectMPRecover   int32 = 82  // Periodic MP recovery every CoolTime ms
	BuffEffectAttrMod     int32 = 201 // Attribute modifier (TypeParam selects attribute)
)

// Attribute TypeParam constants for EffectType == 201 (matching battle_runtime.py).
const (
	AttrAllAtk        int32 = 1
	AttrAllArmor      int32 = 2
	AttrAllPierce     int32 = 3
	AttrPhysAtk       int32 = 4
	AttrEnergyAtk     int32 = 5
	AttrPhysArmor     int32 = 6
	AttrEnergyArmor   int32 = 7
	AttrPhysPierce    int32 = 8
	AttrEnergyPierce  int32 = 9
	AttrAttackSpeed   int32 = 10
	AttrMoveSpeed     int32 = 11
	AttrSkillDmgTaken int32 = 20
	AttrHealMod       int32 = 21
)

// ActiveBuff tracks an active buff or debuff on a battle actor.
type ActiveBuff struct {
	TemplateID     uint32
	InstID         uint32
	CasterID       uint32
	EffectType     int32
	TypeParam      int32
	ValType        int32
	EffectValA     float64
	EffectValB     int32
	TimeEffectValA float64
	StackAdd       float64
	Stacks         uint8
	MaxStacks      uint8
	CoolTime       int32
	Aspect         int32
	FixType        int32
	FixValType     int32
	FixParam       float64
	StartedAt      int64
	NextTickAt     int64
	ExpiresAt      int64 // 0 = permanent until removed
}

// AttrChangeEvent represents a synced attribute change (msg 1560) to send to clients.
type AttrChangeEvent struct {
	CharID     uint32
	UpdateType uint8 // 1 = move speed, 4 = fire interval ms
	Value      int32
}

// isHardCC returns true for control effects blocked by Unstoppable (EffectType 54).
func isHardCC(effectType int32) bool {
	switch effectType {
	case BuffEffectStun, BuffEffectSilence, BuffEffectBanSkills, BuffEffectRoot, BuffEffectConfuse, BuffEffectBanActions:
		return true
	}
	return false
}

// ApplyBuff registers, stacks, or removes a buff/debuff on a member using BuffTemplateData.
// Returns (applied, actualDurationMS, actualStacks). If rejected (e.g. target dead or CC-immune), returns (false, 0, 0).
func (bs *BattleState) ApplyBuff(ev BuffEvent, casterID uint32, nowMS int64) (bool, uint32, uint8) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[ev.TargetID]
	if !ok {
		return false, 0, 0
	}
	if s.ActiveBuffs == nil {
		s.ActiveBuffs = make(map[uint32]ActiveBuff)
	}
	key := ev.InstID
	if key == 0 {
		key = ev.TemplateID
	}
	if ev.Remove {
		delete(s.ActiveBuffs, key)
		return true, 0, 0
	}
	if !s.Alive {
		return false, 0, 0
	}

	tpl, hasTpl := GetBuffTemplate(ev.TemplateID)
	dur := int64(ev.DurationMS)
	if hasTpl && dur <= 0 && tpl.PersistTime > 0 {
		dur = int64(tpl.PersistTime)
	}

	// Check Unstoppable (EffectType 54) against harmful hard CC from enemies.
	if hasTpl && isHardCC(tpl.EffectType) {
		var casterCamp uint8
		if caster, ok := bs.States[casterID]; ok {
			casterCamp = caster.Camp
		}
		if casterCamp != 0 && casterCamp != s.Camp && hasActiveEffectLocked(s, BuffEffectUnstoppable, nowMS) {
			return false, 0, 0
		}
	}

	var expiresAt int64
	if dur > 0 {
		expiresAt = nowMS + dur
	}

	maxStacks := uint8(1)
	if hasTpl && tpl.StackCount > 1 {
		if tpl.StackCount > 255 {
			maxStacks = 255
		} else {
			maxStacks = uint8(tpl.StackCount)
		}
	}

	stacks := ev.Stacks
	if stacks == 0 {
		if existing, exists := s.ActiveBuffs[key]; exists && (existing.ExpiresAt == 0 || nowMS < existing.ExpiresAt) {
			if existing.Stacks < maxStacks {
				stacks = existing.Stacks + 1
			} else {
				stacks = maxStacks
			}
		} else {
			stacks = 1
		}
	} else if stacks > maxStacks {
		stacks = maxStacks
	}

	var nextTickAt int64
	if hasTpl && (tpl.EffectType == BuffEffectPeriodic || tpl.EffectType == BuffEffectMPRecover) && tpl.CoolTime > 0 {
		nextTickAt = nowMS + int64(tpl.CoolTime)
	}

	s.ActiveBuffs[key] = ActiveBuff{
		TemplateID:     ev.TemplateID,
		InstID:         key,
		CasterID:       casterID,
		EffectType:     tpl.EffectType,
		TypeParam:      tpl.TypeParam,
		ValType:        tpl.ValType,
		EffectValA:     tpl.EffectValA,
		EffectValB:     tpl.EffectValB,
		TimeEffectValA: tpl.TimeEffectValA,
		StackAdd:       tpl.StackAdd,
		Stacks:         stacks,
		MaxStacks:      maxStacks,
		CoolTime:       tpl.CoolTime,
		Aspect:         tpl.Aspect,
		FixType:        tpl.FixType,
		FixValType:     tpl.FixValType,
		FixParam:       tpl.FixParam,
		StartedAt:      nowMS,
		NextTickAt:     nextTickAt,
		ExpiresAt:      expiresAt,
	}

	var actualDur uint32
	if dur > 0 {
		actualDur = uint32(dur)
	}
	return true, actualDur, stacks
}

func hasActiveEffectLocked(s *MemberState, effectType int32, nowMS int64) bool {
	for _, b := range s.ActiveBuffs {
		if b.ExpiresAt > 0 && nowMS >= b.ExpiresAt {
			continue // expired — skip but don't delete; tickBuffs handles removal + client notification
		}
		if b.EffectType == effectType {
			return true
		}
	}
	return false
}

// CanMove returns false if the member is stunned (30) or rooted (36).
func (bs *BattleState) CanMove(charID uint32, nowMS int64) bool {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok || s.ActiveBuffs == nil {
		return true
	}
	for _, b := range s.ActiveBuffs {
		if b.ExpiresAt > 0 && nowMS >= b.ExpiresAt {
			continue // expired — skip but don't delete; tickBuffs handles removal + client notification
		}
		if b.EffectType == BuffEffectStun || b.EffectType == BuffEffectRoot {
			return false
		}
	}
	return true
}

// CanCastSlot returns false if the member is stunned, silenced, or banned from using slotNo.
func (bs *BattleState) CanCastSlot(charID uint32, slotNo uint8, nowMS int64) bool {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok || s.ActiveBuffs == nil {
		return true
	}
	var mask int32
	switch slotNo {
	case 0:
		mask = 1
	case 1:
		mask = 2
	case 2:
		mask = 4
	case 10:
		mask = 8
	case 4:
		mask = 16
	}
	for _, b := range s.ActiveBuffs {
		if b.ExpiresAt > 0 && nowMS >= b.ExpiresAt {
			continue // expired — skip but don't delete; tickBuffs handles removal + client notification
		}
		switch b.EffectType {
		case BuffEffectStun:
			return false
		case BuffEffectSilence:
			if slotNo != 0 {
				return false
			}
		case BuffEffectBanSkills:
			if slotNo != 0 && (b.EffectValB == 0 || (mask != 0 && b.EffectValB&mask != 0)) {
				return false
			}
		case BuffEffectBanActions:
			if b.EffectValB == 0 || (mask != 0 && b.EffectValB&mask != 0) {
				return false
			}
		}
	}
	return true
}

// IsStunned returns true if the member has an active stun/knockup buff (EffectType == 30).
func (bs *BattleState) IsStunned(charID uint32, nowMS int64) bool {
	return !bs.CanMove(charID, nowMS)
}

// IsSilenced returns true if the member cannot cast skills (E/Space/R).
func (bs *BattleState) IsSilenced(charID uint32, nowMS int64) bool {
	return !bs.CanCastSlot(charID, 1, nowMS)
}

// Cleanse removes all harmful debuffs (Aspect == -1) from charID and returns removal events.
func (bs *BattleState) Cleanse(charID uint32, nowMS int64) []BuffEvent {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok || s.ActiveBuffs == nil {
		return nil
	}
	var removed []BuffEvent
	for id, b := range s.ActiveBuffs {
		if b.Aspect == -1 {
			delete(s.ActiveBuffs, id)
			removed = append(removed, BuffEvent{
				Remove:   true,
				TargetID: charID,
				InstID:   b.InstID,
			})
		}
	}
	return removed
}

// ClearBuffsOnDeathLocked removes all active buffs on a dead member and emits BuffEvent removals.
func ClearBuffsOnDeathLocked(s *MemberState, memberID uint32, result *TickResult) {
	s.MapAmmoTemplate = 0
	s.MapAmmoRemaining = 0
	s.MapShieldHits = 0
	if s.ActiveBuffs == nil {
		return
	}
	for id, b := range s.ActiveBuffs {
		delete(s.ActiveBuffs, id)
		result.Buffs = append(result.Buffs, BuffEvent{
			Remove:   true,
			TargetID: memberID,
			InstID:   b.InstID,
		})
	}
}

// buffEffectiveVal computes current EffectValA including stacks and time-based decay/ramp.
func buffEffectiveVal(b ActiveBuff, nowMS int64) float64 {
	val := b.EffectValA + b.StackAdd*float64(max(0, int(b.Stacks)-1))
	if b.TimeEffectValA != 0 && b.CoolTime > 0 && nowMS > b.StartedAt {
		steps := (nowMS - b.StartedAt) / int64(b.CoolTime)
		changed := val + b.TimeEffectValA*float64(steps)
		if val > 0 {
			if changed < 0 {
				changed = 0
			}
		} else if val < 0 {
			if changed > 0 {
				changed = 0
			}
		}
		val = changed
	}
	return val
}

// AttrBonusLocked sums percentage (and non-flat) EffectType 201 modifiers matching any of params.
func AttrBonusLocked(s *MemberState, nowMS int64, params ...int32) float64 {
	if s == nil || s.ActiveBuffs == nil {
		return 0
	}
	var total float64
	for _, b := range s.ActiveBuffs {
		if b.ExpiresAt > 0 && nowMS >= b.ExpiresAt {
			continue
		}
		if b.EffectType != BuffEffectAttrMod {
			continue
		}
		matched := false
		for _, p := range params {
			if b.TypeParam == p {
				matched = true
				break
			}
		}
		if !matched {
			continue
		}
		if b.ValType == 1 {
			continue // flat values handled separately
		}
		total += buffEffectiveVal(b, nowMS)
	}
	return total
}

// AttrFlatBonusLocked sums flat (ValType == 1) EffectType 201 modifiers matching any of params.
func AttrFlatBonusLocked(s *MemberState, nowMS int64, params ...int32) float64 {
	if s == nil || s.ActiveBuffs == nil {
		return 0
	}
	var total float64
	for _, b := range s.ActiveBuffs {
		if b.ExpiresAt > 0 && nowMS >= b.ExpiresAt {
			continue
		}
		if b.EffectType != BuffEffectAttrMod || b.ValType != 1 {
			continue
		}
		matched := false
		for _, p := range params {
			if b.TypeParam == p {
				matched = true
				break
			}
		}
		if !matched {
			continue
		}
		total += buffEffectiveVal(b, nowMS)
	}
	return total
}

// CalcMoveSpeedLocked computes current move speed after roots, speed buffs, and strongest slow.
func CalcMoveSpeedLocked(s *MemberState, baseSpeed int32, nowMS int64) int32 {
	if s == nil || baseSpeed <= 0 {
		return baseSpeed
	}
	if hasActiveEffectLocked(s, BuffEffectStun, nowMS) || hasActiveEffectLocked(s, BuffEffectRoot, nowMS) {
		return 0
	}
	var bonusSum, strongestSlow, flat float64
	for _, b := range s.ActiveBuffs {
		if b.ExpiresAt > 0 && nowMS >= b.ExpiresAt {
			continue
		}
		if b.EffectType != BuffEffectAttrMod || b.TypeParam != AttrMoveSpeed {
			continue
		}
		val := buffEffectiveVal(b, nowMS)
		if b.ValType == 1 {
			flat += val
			continue
		}
		if val < 0 {
			if val < strongestSlow {
				strongestSlow = val
			}
		} else {
			bonusSum += val
		}
	}
	mult := 1.0 + bonusSum + strongestSlow
	if mult < 0 {
		mult = 0
	}
	spd := math.Round(float64(baseSpeed)*mult + flat)
	if spd < 0 {
		return 0
	}
	return int32(spd)
}

// CalcFireIntervalLocked computes current basic-attack interval (ms) after attack-speed buffs/debuffs.
func CalcFireIntervalLocked(s *MemberState, baseInterval int32, nowMS int64) int32 {
	if baseInterval <= 0 {
		baseInterval = 500
	}
	if s == nil {
		return baseInterval
	}
	bonus := AttrBonusLocked(s, nowMS, AttrAttackSpeed)
	mult := 1.0 + bonus
	if mult < 0.01 {
		mult = 0.01
	}
	iv := int32(math.Round(float64(baseInterval) / mult))
	if iv < 1 {
		iv = 1
	}
	return iv
}

// DamageModifiersLocked collects multiplicative damage reductions and additive incoming damage bonuses from active buffs.
func DamageModifiersLocked(target *MemberState, isBasic bool, nowMS int64) (reductions []float64, incomingBonus float64) {
	if target == nil || target.ActiveBuffs == nil {
		return nil, 0
	}
	for _, b := range target.ActiveBuffs {
		if b.ExpiresAt > 0 && nowMS >= b.ExpiresAt {
			continue
		}
		switch b.EffectType {
		case BuffEffectDmgReduce:
			r := buffEffectiveVal(b, nowMS)
			if r > 0 && r <= 1 {
				reductions = append(reductions, r)
			}
		case BuffEffectAttrMod:
			if b.TypeParam == AttrSkillDmgTaken && !isBasic {
				// Negative EffectValA (e.g. -0.5) means 50% reduced skill damage taken.
				v := buffEffectiveVal(b, nowMS)
				if v < 0 {
					r := -v
					if r > 1 {
						r = 1
					}
					reductions = append(reductions, r)
				} else if v > 0 {
					incomingBonus += v
				}
			}
		case BuffEffectIncomingAmp:
			v := buffEffectiveVal(b, nowMS)
			if v > 0 {
				incomingBonus += v
			}
		}
	}
	return reductions, incomingBonus
}

// tickBuffs expires timed-out buffs, ticks periodic DoT/HoT buffs, and detects speed/fire-interval changes.
func (bs *BattleState) tickBuffs(now int64, result *TickResult) {
	for memberID, state := range bs.States {
		if state.ActiveBuffs != nil {
			for id, b := range state.ActiveBuffs {
				if b.ExpiresAt > 0 && now >= b.ExpiresAt {
					delete(state.ActiveBuffs, id)
					result.Buffs = append(result.Buffs, BuffEvent{
						Remove:   true,
						TargetID: memberID,
						InstID:   b.InstID,
					})
					continue
				}
				// Periodic DoT / HoT (EffectType == 27)
				if state.Alive && b.EffectType == BuffEffectPeriodic && b.CoolTime > 0 && b.NextTickAt > 0 && now >= b.NextTickAt {
					b.NextTickAt += int64(b.CoolTime)
					state.ActiveBuffs[id] = b
					bs.applyPeriodicBuffTickLocked(memberID, state, b, now, result)
				}
				// Periodic MP recovery (EffectType == 82)
				if state.Alive && b.EffectType == BuffEffectMPRecover && b.CoolTime > 0 && b.NextTickAt > 0 && now >= b.NextTickAt {
					b.NextTickAt += int64(b.CoolTime)
					state.ActiveBuffs[id] = b
					delta := int32(math.Round(buffEffectiveVal(b, now)))
					if delta != 0 && state.MaxMP > 0 {
						before := state.MP
						state.MP += delta
						if state.MP < 0 {
							state.MP = 0
						} else if state.MP > state.MaxMP {
							state.MP = state.MaxMP
						}
						if state.MP != before {
							result.MpChanges = append(result.MpChanges, MpChangeEvent{ObjID: memberID, MP: state.MP})
						}
					}
				}
			}
		}

		if state.Alive {
			// Passive MP regeneration
			if state.MPRecover > 0 && state.MPRecInterv > 0 && state.MaxMP > 0 && now >= state.NextMPRegenAt {
				if state.NextMPRegenAt == 0 {
					state.NextMPRegenAt = now + int64(state.MPRecInterv)
				} else {
					state.NextMPRegenAt += int64(state.MPRecInterv)
					if state.MP < state.MaxMP {
						state.MP += state.MPRecover
						if state.MP > state.MaxMP {
							state.MP = state.MaxMP
						}
						result.MpChanges = append(result.MpChanges, MpChangeEvent{ObjID: memberID, MP: state.MP})
					}
				}
			}
			cfg := GetTankConfig(state.TankID)
			if cfg != nil {
				baseSpeed := int32(cfg.MoveSpeed)
				if baseSpeed <= 0 {
					baseSpeed = 160
				}
				curSpeed := CalcMoveSpeedLocked(state, baseSpeed, now)
				if curSpeed != state.LastSyncSpeed {
					state.LastSyncSpeed = curSpeed
					result.AttrChanges = append(result.AttrChanges, AttrChangeEvent{
						CharID:     memberID,
						UpdateType: 1,
						Value:      curSpeed,
					})
				}

				baseFire := int32(cfg.FireRateMS)
				if baseFire <= 0 {
					baseFire = 500
				}
				curFire := CalcFireIntervalLocked(state, baseFire, now)
				if curFire != state.LastSyncFireMS {
					state.LastSyncFireMS = curFire
					result.AttrChanges = append(result.AttrChanges, AttrChangeEvent{
						CharID:     memberID,
						UpdateType: 4,
						Value:      curFire,
					})
				}
			}
		}
	}
}

func (bs *BattleState) applyPeriodicBuffTickLocked(memberID uint32, state *MemberState, b ActiveBuff, now int64, result *TickResult) {
	val := buffEffectiveVal(b, now)
	if b.FixParam != 0 {
		switch b.FixValType {
		case 2: // % of target MaxHP
			val += float64(state.MaxHP) * b.FixParam
		case 1, 11: // % of caster ATK
			if caster, ok := bs.States[b.CasterID]; ok {
				if cfg := GetTankConfig(caster.TankID); cfg != nil {
					atk := cfg.Combat.Attack
					if cfg.Combat.EnergyAtk > atk {
						atk = cfg.Combat.EnergyAtk
					}
					val += atk * b.FixParam
				}
			}
		}
	}
	if val == 0 {
		return
	}
	if val > 0 {
		// HoT heal
		healMod := 1.0 + AttrBonusLocked(state, now, AttrHealMod)
		if healMod < 0 {
			healMod = 0
		}
		healAmt := int32(math.Round(val * healMod))
		if healAmt <= 0 || state.HP >= state.MaxHP {
			return
		}
		hpBefore := state.HP
		state.HP += healAmt
		if state.HP > state.MaxHP {
			state.HP = state.MaxHP
		}
		delta := state.HP - hpBefore
		if delta > 0 {
			result.HpChanges = append(result.HpChanges, HpChangeEvent{ObjID: memberID, HP: state.HP})
			result.HpDeltas = append(result.HpDeltas, HpDeltaEvent{ObjID: memberID, Delta: delta, CasterID: b.CasterID})
		}
		return
	}

	// DoT damage
	dmg := int32(math.Round(-val))
	if dmg <= 0 {
		return
	}
	var immune bool
	dmg, immune = applyDefenseModifiers(state, dmg, now)
	if immune || dmg <= 0 {
		return
	}

	hpBefore := state.HP
	shieldAbsorbed := int32(0)
	if state.Shield > 0 {
		if state.Shield >= dmg {
			state.Shield -= dmg
			shieldAbsorbed = dmg
			dmg = 0
		} else {
			shieldAbsorbed = state.Shield
			dmg -= state.Shield
			state.Shield = 0
		}
		result.ShieldChanges = append(result.ShieldChanges, ShieldChangeEvent{ObjID: memberID, Shield: state.Shield})
	}
	state.HP -= dmg
	if state.HP < 0 {
		state.HP = 0
	}
	hpLoss := hpBefore - state.HP
	if caster, ok := bs.States[b.CasterID]; ok {
		caster.DamageOut += shieldAbsorbed + hpLoss
	}
	result.HpChanges = append(result.HpChanges, HpChangeEvent{ObjID: memberID, HP: state.HP})
	delta := state.HP - hpBefore
	if shieldAbsorbed > 0 && delta == 0 {
		delta = -shieldAbsorbed
	}
	if delta != 0 {
		result.HpDeltas = append(result.HpDeltas, HpDeltaEvent{ObjID: memberID, Delta: delta, CasterID: b.CasterID})
	}

	if state.HP <= 0 {
		state.Alive = false
		state.Deaths++
		elapsed := now - bs.StartTime
		state.RespawnAt = now + RespawnDelay(elapsed)
		ClearBuffsOnDeathLocked(state, memberID, result)

		var killerCamp uint8
		if caster, ok := bs.States[b.CasterID]; ok {
			caster.Kills++
			killerCamp = caster.Camp
			if bs.ModeType != 1 && bs.ModeType != 2 {
				bs.Scores[killerCamp]++
			}
		}
		result.Deaths = append(result.Deaths, DeathEvent{
			VictimID: memberID,
			KillerID: b.CasterID,
		})
		if bs.ModeType != 1 && bs.ModeType != 2 && bs.WinTarget > 0 && killerCamp > 0 && bs.Scores[killerCamp] >= bs.WinTarget {
			bs.Finished = true
			bs.Winner = killerCamp
			result.GameOver = true
			result.Winner = killerCamp
			result.Scores = bs.Scores
			result.ElapsedMS = int32(elapsed)
		}
	}
}
