package game

import "math"

func (bs *BattleState) tickRepairBoxes(positions map[uint32]*MemberPos, now int64, result *TickResult) {
	for _, npc := range bs.NPCs {
		if !npc.Alive || npc.Type != 6 {
			continue
		}
		if npc.RepairTarget != 0 {
			target := bs.States[npc.RepairTarget]
			if target == nil || !target.Alive || npc.RepairTicksLeft <= 0 {
				result.Buffs = append(result.Buffs,
					BuffEvent{Remove: true, TargetID: npc.ID, InstID: 40001},
					BuffEvent{Remove: true, TargetID: npc.RepairTarget, InstID: 10},
				)
				npc.RepairTarget = 0
				npc.RepairTicksLeft = 0
				continue
			}
			if now >= npc.RepairNextAt {
				heal := int32(math.Round(float64(target.MaxHP) * 0.04))
				if heal < 1 {
					heal = 1
				}
				hpBefore := target.HP
				target.HP += heal
				if target.HP > target.MaxHP {
					target.HP = target.MaxHP
				}
				actualHeal := target.HP - hpBefore
				if actualHeal > 0 {
					result.HpChanges = append(result.HpChanges, HpChangeEvent{
						ObjID: npc.RepairTarget,
						HP:    target.HP,
					})
					result.HpDeltas = append(result.HpDeltas, HpDeltaEvent{
						ObjID:    npc.RepairTarget,
						Delta:    actualHeal,
						Crit:     false,
						CasterID: npc.ID,
					})
				}
				npc.RepairTicksLeft--
				npc.RepairNextAt += 1000
				if npc.RepairTicksLeft <= 0 {
					result.Buffs = append(result.Buffs,
						BuffEvent{Remove: true, TargetID: npc.ID, InstID: 40001},
						BuffEvent{Remove: true, TargetID: npc.RepairTarget, InstID: 10},
					)
					npc.RepairTarget = 0
				}
			}
			continue
		}

		// Idle box: check if any eligible ally tank is within 60px of box edge
		halfW := float64(npc.Width) / 2.0
		halfH := float64(npc.Height) / 2.0
		if halfW <= 0 {
			halfW = 36
		}
		if halfH <= 0 {
			halfH = 36
		}
		for memberID, state := range bs.States {
			if !state.Alive || state.HP >= state.MaxHP || now < state.RepairReadyAt {
				continue
			}
			if npc.Camp != 0 && npc.Camp != state.Camp {
				continue
			}
			pos := positions[memberID]
			if pos == nil {
				continue
			}
			if math.Abs(float64(pos.X-npc.X)) <= halfW+60.0 && math.Abs(float64(pos.Y-npc.Y)) <= halfH+60.0 {
				npc.RepairTarget = memberID
				npc.RepairTicksLeft = 5
				npc.RepairNextAt = now + 1000
				state.RepairReadyAt = now + 15000
				result.Buffs = append(result.Buffs,
					BuffEvent{TargetID: npc.ID, TemplateID: 40001, InstID: 40001, Stacks: 1, DurationMS: 5000},
					BuffEvent{TargetID: memberID, TemplateID: 10, InstID: 10, Stacks: 1, DurationMS: 5000},
					BuffEvent{TargetID: memberID, TemplateID: 11, InstID: 11, Stacks: 1, DurationMS: 15000},
				)
				break
			}
		}
	}
}

// determineWinner decides who wins when time runs out.
// 1. Primary objective (Base HP% in ModeType 1, Scores in ModeType 2/3).
// 2. If tied: side with fewer deaths (lower score against them) wins.
// 3. If still equal: random camp 1 or 2.
