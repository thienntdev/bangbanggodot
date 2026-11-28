package game

import (
	"os"
	"path/filepath"
	"testing"
)

func TestItemCatalog_BagAndEventsJSON(t *testing.T) {
	cat := NewItemCatalog()

	bagPath := filepath.Join("..", "..", "server", "public", "godot", "a", "l", "bag.json")
	if _, err := os.Stat(bagPath); err != nil {
		t.Skip("bag.json not present in workspace")
	}
	if err := cat.LoadBagJSON(bagPath); err != nil {
		t.Fatalf("LoadBagJSON failed: %v", err)
	}
	if len(cat.Presents) < 700 {
		t.Fatalf("expected >=700 presents, got %d", len(cat.Presents))
	}

	// Verify 2004393 (10 xu khóa)
	rewards, err := cat.OpenPresent(2004393, 2)
	if err != nil || len(rewards) != 1 {
		t.Fatalf("OpenPresent(2004393, 2) unexpected: %v, %+v", err, rewards)
	}
	if rewards[0].Kind != "currency" || rewards[0].CurrName != "gift" || rewards[0].Quantity != 20 {
		t.Fatalf("expected 20 gift (xu khóa), got %+v", rewards[0])
	}

	// Verify 2002128 (multi-reward present: items + cash)
	multi, err := cat.OpenPresent(2002128, 1)
	if err != nil || len(multi) != 5 {
		t.Fatalf("OpenPresent(2002128, 1) unexpected: %v, len=%d", err, len(multi))
	}

	eventsPath := filepath.Join("..", "..", "server", "public", "godot", "a", "l", "events.json")
	if err := cat.LoadEventsJSON(eventsPath); err != nil {
		t.Fatalf("LoadEventsJSON failed: %v", err)
	}
	if len(cat.GetSignInDailyRewards(0)) == 0 {
		t.Fatalf("expected Sunday daily rewards")
	}
	if len(cat.GetSignInMarkRewards(5)) == 0 {
		t.Fatalf("expected 5-day mark rewards")
	}
	if len(cat.GetSignInVipRewards(1)) == 0 {
		t.Fatalf("expected VIP 1 rewards")
	}

	// Test GrantBoxRewards updates character wallet & inventory
	store := NewStore()
	ch := &Character{CharID: 1, Name: "Tester"}
	store.mu.Lock()
	store.characters[1] = ch
	store.mu.Unlock()

	added := store.GrantBoxRewards(1, rewards, cat)
	if len(added) != 0 || ch.Golden != 20 {
		t.Fatalf("expected Golden=20, got %d (added=%d)", ch.Golden, len(added))
	}

	addedMark := store.GrantBoxRewards(1, cat.GetSignInMarkRewards(5), cat)
	if len(addedMark) == 0 || ch.Golden != 70 || ch.Silver != 10000 {
		t.Fatalf("expected Golden=70, Silver=10000, addedMark>0; got Golden=%d Silver=%d added=%d", ch.Golden, ch.Silver, len(addedMark))
	}
}

func TestValidateCanOpenBox_DuplicateAndBagFull(t *testing.T) {
	cat := NewItemCatalog()
	cat.Boxes[2005025] = &BoxDef{
		ItemID:          2005025,
		Name:            "Trứng Hỏa Kỳ Lân",
		Mode:            "random",
		MainPercent:     10,
		MaterialPercent: 90,
		DuplicatePolicy: "reject_owned_unique_main",
		MainRewards: []BoxReward{
			{Kind: "item", ID: float64(4431007), Quantity: 1},
		},
		MaterialRewards: []BoxReward{
			{Kind: "item", ID: float64(3000148), Quantity: 1},
		},
	}
	cat.Boxes[2009302] = &BoxDef{
		ItemID:          2009302,
		Name:            "Trứng Xe Bí Ngô",
		Mode:            "random",
		MainPercent:     10,
		MaterialPercent: 90,
		DuplicatePolicy: "reject_owned_unique_main",
		MainRewards: []BoxReward{
			{Kind: "tank", ID: float64(10000052), Quantity: 1},
		},
		MaterialRewards: []BoxReward{
			{Kind: "item", ID: float64(3000148), Quantity: 1},
		},
	}

	store := NewStore()
	ch := &Character{CharID: 1, Name: "Tester"}
	store.mu.Lock()
	store.characters[1] = ch
	store.mu.Unlock()

	// 1. Clean character → allowed
	if err := cat.ValidateCanOpenBox(store, 1, 2005025); err != nil {
		t.Fatalf("expected allowed, got %v", err)
	}

	// 2. Owns permanent helper 4431007 → rejected
	store.mu.Lock()
	ch.Items = append(ch.Items, PlayerItem{ContType: 5, SlotNo: 0, TemplateID: 4431007, Count: 1, LifeTime: 0})
	store.mu.Unlock()
	if err := cat.ValidateCanOpenBox(store, 1, 2005025); err == nil {
		t.Fatalf("expected already_owned error for helper 4431007")
	}

	// 3. Owns permanent tank 10000052 → rejected
	store.mu.Lock()
	ch.Tanks = append(ch.Tanks, PlayerTank{TankID: 10000052, ExistTime: 0})
	store.mu.Unlock()
	if err := cat.ValidateCanOpenBox(store, 1, 2009302); err == nil {
		t.Fatalf("expected already_owned error for tank 10000052")
	}

	// 4. Container 3 full (135 slots) and 3000148 not present → rejected
	store.mu.Lock()
	ch.Items = nil // clear helper
	for i := 0; i < 135; i++ {
		ch.Items = append(ch.Items, PlayerItem{ContType: 3, SlotNo: int16(i), TemplateID: uint32(3990000 + i), Count: 1})
	}
	store.mu.Unlock()
	if err := cat.ValidateCanOpenBox(store, 1, 2005025); err == nil {
		t.Fatalf("expected bag_full error when container 3 has 135 items")
	}

	// 5. Stackable onto existing 3000148 even when full → allowed
	store.mu.Lock()
	ch.Items[0].TemplateID = 3000148
	store.mu.Unlock()
	if err := cat.ValidateCanOpenBox(store, 1, 2005025); err != nil {
		t.Fatalf("expected allowed when material stacks onto existing slot, got %v", err)
	}
}
