package game

import (
	"testing"
)

func TestAimed(t *testing.T) {
	// 1. fixed = true: always projects exactly distance
	// Start (100, 100), Dest (110, 100), distance 384
	x, y := Aimed(100, 100, 110, 100, 384, true)
	if x != 484 || y != 100 {
		t.Errorf("Aimed(fixed=true) short click expected (484, 100), got (%d, %d)", x, y)
	}

	// 2. fixed = false (e.g. Wukong Space blink):
	// Player clicks at (150, 100) (distance 50 < 264 max range)
	// Must land at (150, 100) exactly, NOT overshoot!
	x, y = Aimed(100, 100, 150, 100, 264, false)
	if x != 150 || y != 100 {
		t.Errorf("Aimed(fixed=false) short click expected (150, 100), got (%d, %d)", x, y)
	}

	// Player clicks at (500, 100) (distance 400 > 264 max range)
	// Must cap at 100 + 264 = 364
	x, y = Aimed(100, 100, 500, 100, 264, false)
	if x != 364 || y != 100 {
		t.Errorf("Aimed(fixed=false) long click expected (364, 100), got (%d, %d)", x, y)
	}
}

func TestClearTankLanding_CrossInnerWall(t *testing.T) {
	// Thin inner wall located at X: [200, 240], Y: [100, 300]
	walls := []WallRect{
		{Left: 200, Top: 100, Right: 240, Bottom: 300},
	}
	b := ArenaBounds{Left: 36, Top: 36, Right: 2000, Bottom: 2000}

	// Tank starts at (100, 200) and dashes/blinks to (400, 200)
	// The destination (400, 200) has its padded body [364, 436] completely clear of [200, 240].
	// Following Python clear_tank_landing: tank CAN cross inner wall if destination is open ground.
	landX, landY := ClearTankLanding(walls, 100, 200, 400, 200, b)
	if landX != 400 || landY != 200 {
		t.Errorf("Expected tank to jump across inner wall to (400, 200), got (%d, %d)", landX, landY)
	}
}

func TestClearTankLanding_BlockedBySolidWall(t *testing.T) {
	// Wide solid wall located at X: [200, 500], Y: [100, 300]
	walls := []WallRect{
		{Left: 200, Top: 100, Right: 500, Bottom: 300},
	}
	b := ArenaBounds{Left: 36, Top: 36, Right: 2000, Bottom: 2000}

	landX, landY := ClearTankLanding(walls, 100, 200, 300, 200, b)
	if landX != 164 || landY != 200 {
		t.Errorf("Expected tank to stop at wall front edge (164, 200), got (%d, %d)", landX, landY)
	}
}

func TestWukongSkills_LandingAndMoves(t *testing.T) {
	behavior := &WukongBehavior{}
	walls := []WallRect{
		// Thin wall from 200 to 240
		{Left: 200, Top: 100, Right: 240, Bottom: 300},
	}

	ctx := &ActorContext{
		ActorID: 101,
		PosX:    100,
		PosY:    200,
		Walls:   walls,
		Bounds:  ArenaBounds{Left: 36, Top: 36, Right: 2000, Bottom: 2000},
	}

	// 1. Wukong E (slot 1): Dash 384px to the right across the wall
	resE := behavior.OnUseSkill(ctx, 1, 0, 200, 200)
	if len(resE.Moves) != 1 {
		t.Fatalf("Expected 1 MoveEvent for E, got %d", len(resE.Moves))
	}
	// Destination should be 100 + 384 = 484 (across the wall at 200..240)
	if resE.Moves[0].DestX != 484 || resE.Moves[0].DestY != 200 {
		t.Errorf("Wukong E expected destination (484, 200), got (%d, %d)", resE.Moves[0].DestX, resE.Moves[0].DestY)
	}
	if resE.Moves[0].MoveType != 3 || resE.Moves[0].Speed != 960 {
		t.Errorf("Wukong E expected MoveType 3, Speed 960, got MoveType %d, Speed %d", resE.Moves[0].MoveType, resE.Moves[0].Speed)
	}

	// 2. Wukong Space (slot 2): Blink across the wall to close click (e.g. 260px away)
	resSpace := behavior.OnUseSkill(ctx, 2, 0, 360, 200)
	if len(resSpace.Moves) != 1 {
		t.Fatalf("Expected 1 MoveEvent for Space, got %d", len(resSpace.Moves))
	}
	// Distance is 260 <= 264, destination is 360 (across the wall at 200..240)
	if resSpace.Moves[0].DestX != 360 || resSpace.Moves[0].DestY != 200 {
		t.Errorf("Wukong Space expected destination (360, 200), got (%d, %d)", resSpace.Moves[0].DestX, resSpace.Moves[0].DestY)
	}
	// Space must be instant teleport MoveType 5, Speed 0 (stop/halt)
	if resSpace.Moves[0].MoveType != 5 || resSpace.Moves[0].Speed != 0 {
		t.Errorf("Wukong Space expected MoveType 5, Speed 0, got MoveType %d, Speed %d", resSpace.Moves[0].MoveType, resSpace.Moves[0].Speed)
	}
}

func TestGundamR_RecoilLanding(t *testing.T) {
	behavior := &GundamBehavior{}
	walls := []WallRect{
		// Thin wall behind Gundam at X: [150, 180]
		{Left: 150, Top: 100, Right: 180, Bottom: 300},
	}

	// Gundam at (300, 200), fires shot to the right (500, 200).
	// Recoil is 300px to the left (X=0, clamped to arena min 40).
	// Across the thin wall at [150, 180], destination at X=40 has body [4, 76] completely clear of [150, 180].
	ctx := &ActorContext{
		ActorID: 102,
		PosX:    300,
		PosY:    200,
		Walls:   walls,
		Bounds:  ArenaBounds{Left: 40, Top: 40, Right: 2000, Bottom: 2000},
	}

	resR := behavior.OnUseSkill(ctx, 10, 0, 500, 200)
	if len(resR.Moves) != 1 {
		t.Fatalf("Expected 1 MoveEvent for R recoil, got %d", len(resR.Moves))
	}
	if resR.Moves[0].DestX != 40 || resR.Moves[0].DestY != 200 {
		t.Errorf("Gundam R recoil expected destination (40, 200), got (%d, %d)", resR.Moves[0].DestX, resR.Moves[0].DestY)
	}
}
