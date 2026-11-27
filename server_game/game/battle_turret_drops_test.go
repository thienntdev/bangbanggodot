package game

import "testing"

func TestTurretAIFiresAtNearestEnemy(t *testing.T) {
	bs := NewBattleState(60000)
	bs.AddMember(1, 1000, 1, 10000019, 100, 100)
	bs.AddMember(2, 1000, 2, 10000036, 300, 100)
	bs.NPCs = map[uint32]*MapNPC{
		234881025: {
			ID:             234881025,
			Template:       9001,
			X:              120,
			Y:              100,
			HP:             2000,
			MaxHP:          2000,
			Camp:           1,
			Type:           4,
			Alive:          true,
			Attack:         150,
			FireIntervalMS: 1000,
			AlertRange:     400,
			TurretSkill:    301,
		},
	}

	positions := map[uint32]*MemberPos{
		1: {X: 100, Y: 100},
		2: {X: 300, Y: 100},
	}

	var res TickResult
	now := int64(50000)
	bs.mu.Lock()
	bs.tickTurrets(positions, now, &res)
	bs.mu.Unlock()

	if len(res.TurretFires) != 1 {
		t.Fatalf("expected 1 turret fire, got %d", len(res.TurretFires))
	}
	if res.TurretFires[0].DestX != 300 || res.TurretFires[0].DestY != 100 {
		t.Fatalf("expected turret to target enemy at (300,100), got (%d,%d)", res.TurretFires[0].DestX, res.TurretFires[0].DestY)
	}
	if len(bs.Bullets) != 1 {
		t.Fatalf("expected 1 registered turret bullet, got %d", len(bs.Bullets))
	}
}

func TestMapDropsShieldHealAndAmmo(t *testing.T) {
	bs := NewBattleState(60000)
	bs.AddMember(1, 1000, 1, 10000019, 100, 100)
	bs.States[1].HP = 800 // injured

	bs.Drops = map[uint32]*MapDrop{
		1001: {ID: 1001, Template: 412, X: 110, Y: 100}, // +10% MaxHP heal (100)
		1002: {ID: 1002, Template: 413, X: 110, Y: 100}, // 3-hit shield
		1003: {ID: 1003, Template: 105, X: 110, Y: 100}, // triple spread ammo (15 shots)
	}
	positions := map[uint32]*MemberPos{
		1: {X: 100, Y: 100},
	}

	var res TickResult
	now := int64(50000)
	bs.mu.Lock()
	bs.tickDrops(positions, now, &res)
	bs.mu.Unlock()

	if bs.States[1].HP != 900 {
		t.Fatalf("expected HP 900 after 412 heal, got %d", bs.States[1].HP)
	}
	if bs.States[1].MapShieldHits != 3 {
		t.Fatalf("expected 3 shield hits after 413 pickup, got %d", bs.States[1].MapShieldHits)
	}
	if len(res.RemovedObjects) != 3 {
		t.Fatalf("expected 3 drops removed, got %d", len(res.RemovedObjects))
	}

	// Verify 3-hit shield absorbs damage
	dmg, immune := applyDefenseModifiers(bs.States[1], 200, now)
	if !immune || dmg != 0 || bs.States[1].MapShieldHits != 2 {
		t.Fatalf("expected 1st hit absorbed (hits left=2), got dmg=%d immune=%v hits=%d", dmg, immune, bs.States[1].MapShieldHits)
	}

	// Verify 105 triple spread ammo produces 2 extra angled bullets
	extra, rem := bs.ConsumeMapAmmoShot(1, FireEvent{
		Template: 302600, StartX: 100, StartY: 100, DestX: 500, DestY: 100, Speed: 800, Basic: true,
	})
	if len(extra) != 2 || len(rem) != 0 || bs.States[1].MapAmmoRemaining != 14 {
		t.Fatalf("expected 2 extra spread bullets and 14 remaining, got extra=%d rem=%d left=%d", len(extra), len(rem), bs.States[1].MapAmmoRemaining)
	}
}

func TestBulletHitsDestructibleNPCEdge(t *testing.T) {
	npcs := map[uint32]*MapNPC{
		1: {ID: 1, X: 200, Y: 100, HP: 100, MaxHP: 100, Camp: 0, Width: 72, Height: 72, Type: 1, Alive: true},
	}
	// Bullet aimed at center of NPC (200, 100) from (50, 100)
	hit, frac := CheckBulletNPCCollisionSegment(npcs, 50, 100, 200, 100, 1)
	if hit == nil || hit.NpcID != 1 || frac <= 0 || frac >= 1 {
		t.Fatalf("expected NPC hit along segment, got hit=%v frac=%v", hit, frac)
	}
}
