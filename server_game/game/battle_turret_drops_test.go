package game

import (
	"testing"
	"time"
)

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
	hit, frac := CheckBulletNPCCollisionSegment(npcs, 50, 100, 200, 100, 1, 0) // ownerID=0 → player bullet
	if hit == nil || hit.NpcID != 1 || frac <= 0 || frac >= 1 {
		t.Fatalf("expected NPC hit along segment, got hit=%v frac=%v", hit, frac)
	}
}

func TestAreaHitsDestructibleNPCAndRemovesOnDeath(t *testing.T) {
	bs := NewBattleState(60000)
	bs.AddMember(1, 1000, 1, 10000036, 100, 100)
	bs.NPCs = map[uint32]*MapNPC{
		234881024: {
			ID:       234881024,
			Template: 2003,
			X:        160,
			Y:        100,
			HP:       50,
			MaxHP:    100,
			Camp:     0,
			Width:    72,
			Height:   72,
			Type:     1,
			Alive:    true,
		},
	}
	positions := map[uint32]*MemberPos{
		1: {X: 100, Y: 100},
	}

	// 1. Wukong cone empowered attack hitting the box
	res, _ := bs.ApplyAreaHit(1, 1, AreaHitEvent{
		Shape:      "cone",
		Template:   310121,
		StartX:     100,
		StartY:     100,
		DestX:      200,
		DestY:      100,
		Radius:     192,
		AngleDeg:   180,
		DamageMult: 1.0,
	}, positions, 1000)

	npc := bs.NPCs[234881024]
	if len(res.HpChanges) != 1 || res.HpChanges[0].ObjID != 234881024 {
		t.Fatalf("expected HpChanges for NPC, got %+v", res.HpChanges)
	}
	if npc.HP != 25 {
		t.Fatalf("expected NPC HP 25 (50 - 100/4), got %d", npc.HP)
	}

	// 2. Second hit destroys the box
	res2, _ := bs.ApplyAreaHit(1, 1, AreaHitEvent{
		Shape:      "circle",
		Template:   310401,
		StartX:     100,
		StartY:     100,
		DestX:      100,
		DestY:      100,
		Radius:     216,
		DamageMult: 1.0,
	}, positions, 2000)

	if npc.Alive {
		t.Fatalf("expected NPC to be destroyed")
	}
	if len(res2.RemovedObjects) != 1 || res2.RemovedObjects[0] != 234881024 {
		t.Fatalf("expected RemovedObjects to contain 234881024, got %+v", res2.RemovedObjects)
	}
}

func TestBulletTickHitsDestructibleNPCAndDeductsHP(t *testing.T) {
	bs := NewBattleState(60000)
	bs.AddMember(1, 1000, 1, 10000036, 100, 100)
	bs.NPCs = map[uint32]*MapNPC{
		234881024: {
			ID:       234881024,
			Template: 2003,
			X:        300,
			Y:        100,
			HP:       100,
			MaxHP:    100,
			Camp:     0,
			Width:    72,
			Height:   72,
			Type:     1,
			Alive:    true,
		},
	}
	positions := map[uint32]*MemberPos{
		1: {X: 100, Y: 100},
	}

	now := time.Now().UnixMilli()
	bs.StartTime = now - 220
	bs.Deadline = now + 60000

	// Bullet flies from 100 to 500 at speed 1000 px/s (takes 400ms)
	// Started 220ms ago, so at Tick (now) bullet has traveled 220px to X=320 (penetrating box at X=300)
	bs.AddBullet(&BulletFlight{
		ID:        999,
		OwnerID:   1,
		Camp:      1,
		Template:  310101,
		StartX:    100,
		StartY:    100,
		DestX:     500,
		DestY:     100,
		Speed:     1000,
		StartTime: now - 220,
		LifeMS:    400,
		Power:     100,
		HitsWall:  false,
	})

	res := bs.Tick(positions)

	npc := bs.NPCs[234881024]
	if npc.HP != 75 {
		t.Fatalf("expected NPC HP 75 (100 - 100/4), got %d", npc.HP)
	}
	if len(res.HpChanges) != 1 || res.HpChanges[0].ObjID != 234881024 || res.HpChanges[0].HP != 75 {
		t.Fatalf("expected HpChanges for NPC with HP=75, got %+v", res.HpChanges)
	}
	if len(res.BlownBullets) != 1 || res.BlownBullets[0].BulletID != 999 {
		t.Fatalf("expected BlownBullets to contain bullet 999, got %+v", res.BlownBullets)
	}
	if len(res.ExpiredIDs) != 1 || res.ExpiredIDs[0] != 999 {
		t.Fatalf("expected ExpiredIDs (m_overVec) to contain bullet 999, got %+v", res.ExpiredIDs)
	}
	if _, ok := bs.Bullets[999]; ok {
		t.Fatalf("expected bullet 999 to be removed from bs.Bullets")
	}
}
