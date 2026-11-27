package game

import "testing"

func newTestBattleForBuffs() *BattleState {
	bs := &BattleState{
		States: map[uint32]*MemberState{
			1: {HP: 1000, MaxHP: 1000, Alive: true, Camp: 1, TankID: 10000019},
			2: {HP: 1000, MaxHP: 1000, Alive: true, Camp: 2, TankID: 10000036},
		},
		StartTime: 1000,
		WinTarget: 5,
	}
	return bs
}

func TestBuffCCAndUnstoppable(t *testing.T) {
	bs := newTestBattleForBuffs()
	now := int64(2000)

	// Stun (template 216 has EffectType 30, PersistTime 10000)
	applied, dur, _ := bs.ApplyBuff(BuffEvent{TargetID: 2, TemplateID: 216, InstID: 216}, 1, now)
	if !applied || dur != 10000 {
		t.Fatalf("expected stun applied for 10000ms, got applied=%v dur=%d", applied, dur)
	}
	if bs.CanMove(2, now+100) {
		t.Fatalf("expected stunned actor unable to move")
	}
	if bs.CanCastSlot(2, 0, now+100) || bs.CanCastSlot(2, 1, now+100) {
		t.Fatalf("expected stunned actor unable to attack or cast")
	}

	// Cleanse removes Aspect == -1 debuffs; manually test Cleanse with a debuff
	bs.ApplyBuff(BuffEvent{TargetID: 2, InstID: 216, Remove: true}, 1, now+200)
	if !bs.CanMove(2, now+200) {
		t.Fatalf("expected actor able to move after stun removed")
	}

	// Unstoppable (template 392311 has EffectType 54) blocks enemy hard CC
	applied, _, _ = bs.ApplyBuff(BuffEvent{TargetID: 2, TemplateID: 392311, InstID: 392311}, 2, now+300)
	if !applied {
		t.Fatalf("expected unstoppable applied")
	}
	applied, _, _ = bs.ApplyBuff(BuffEvent{TargetID: 2, TemplateID: 216, InstID: 216}, 1, now+400)
	if applied {
		t.Fatalf("expected unstoppable to reject enemy stun")
	}
}

func TestBuffSpeedAndSlowAggregation(t *testing.T) {
	bs := newTestBattleForBuffs()
	now := int64(5000)
	s := bs.States[2]

	// Apply two slows: 220 (-0.5) and 222 (-0.7) -> strongest slow (-0.7) wins, not -1.2
	bs.ApplyBuff(BuffEvent{TargetID: 2, TemplateID: 220, InstID: 220}, 1, now)
	bs.ApplyBuff(BuffEvent{TargetID: 2, TemplateID: 222, InstID: 222}, 1, now)
	// Apply speed buff 511102 (+0.42) -> 1 + 0.42 - 0.70 = 0.72
	bs.ApplyBuff(BuffEvent{TargetID: 2, TemplateID: 511102, InstID: 511102}, 2, now)

	bs.mu.Lock()
	spd := CalcMoveSpeedLocked(s, 200, now+100)
	bs.mu.Unlock()
	if spd != 144 {
		t.Fatalf("expected speed 144 (200 * 0.72), got %d", spd)
	}
}

func TestPeriodicDoTAndHoT(t *testing.T) {
	bs := newTestBattleForBuffs()
	now := int64(10000)

	// Template 23: EffectType 27, EffectValA -120, PersistTime 3000, CoolTime 1000
	applied, _, _ := bs.ApplyBuff(BuffEvent{TargetID: 2, TemplateID: 23, InstID: 23}, 1, now)
	if !applied {
		t.Fatalf("expected DoT applied")
	}

	var res TickResult
	bs.mu.Lock()
	bs.tickBuffs(now+1000, &res)
	bs.mu.Unlock()

	if bs.States[2].HP != 880 {
		t.Fatalf("expected HP 880 after 120 DoT tick, got %d", bs.States[2].HP)
	}
	if bs.States[1].DamageOut != 120 {
		t.Fatalf("expected caster DamageOut 120, got %d", bs.States[1].DamageOut)
	}

	// Template 10: EffectType 27, EffectValA +75, FixValType 2, FixParam 0.05 -> 75 + 1000*0.05 = 125 heal
	applied, _, _ = bs.ApplyBuff(BuffEvent{TargetID: 2, TemplateID: 10, InstID: 10}, 2, now+1000)
	if !applied {
		t.Fatalf("expected HoT applied")
	}
	var res2 TickResult
	bs.mu.Lock()
	bs.tickBuffs(now+2000, &res2)
	bs.mu.Unlock()
	// At now+2000: DoT ticks (-120 -> 760) AND HoT ticks (+125 -> 885)
	if bs.States[2].HP != 885 {
		t.Fatalf("expected HP 885 after DoT(-120) and HoT(+125), got %d", bs.States[2].HP)
	}
}

func TestMPSystemAndRegen(t *testing.T) {
	bs := newTestBattleForBuffs()
	bs.SetMemberMP(1, 100, 100, 5, 1000)

	if !bs.HasEnoughMP(1, 50) {
		t.Fatalf("expected enough MP for 50")
	}
	newMP, ok := bs.ConsumeMP(1, 60)
	if !ok || newMP != 40 {
		t.Fatalf("expected ConsumeMP(60) -> 40, got %d (ok=%v)", newMP, ok)
	}
	if bs.HasEnoughMP(1, 50) {
		t.Fatalf("expected insufficient MP for 50 when at 40")
	}

	// Passive regen tick
	now := int64(20000)
	bs.States[1].NextMPRegenAt = now
	var res TickResult
	bs.mu.Lock()
	bs.tickBuffs(now, &res)
	bs.mu.Unlock()
	if bs.States[1].MP != 45 {
		t.Fatalf("expected passive MP regen to 45, got %d", bs.States[1].MP)
	}

	// BuffEffectMPRecover (82): template 392303 grants +25 MP every 1000ms
	bs.ApplyBuff(BuffEvent{TargetID: 1, TemplateID: 392303, InstID: 392303}, 1, now)
	var res2 TickResult
	bs.mu.Lock()
	bs.tickBuffs(now+1000, &res2)
	bs.mu.Unlock()
	// Passive +5 and Buff +25 => 45 + 5 + 25 = 75
	if bs.States[1].MP != 75 {
		t.Fatalf("expected MP 75 after passive (+5) and buff (+25), got %d", bs.States[1].MP)
	}
}
