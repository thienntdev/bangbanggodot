package game

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
	"log"
	"math/big"
	"os"
	"strconv"
	"time"
)

// ============================================================================
// Item Catalog & Gift Box System
// Loads box definitions from normal_shop_catalog.json and handles gift box
// opening with random/fixed rewards.
// ============================================================================

// BoxReward represents a single reward entry in a box definition.
type BoxReward struct {
	Kind     string `json:"kind"`     // "item", "tank", "currency"
	ID       interface{} `json:"id"` // uint32 for items/tanks, string for currency
	Quantity int32  `json:"quantity"`
}

// BoxDef represents a gift box / egg definition.
type BoxDef struct {
	ItemID          uint32      `json:"itemId"`
	Name            string      `json:"name"`
	Mode            string      `json:"mode"` // "fixed" or "random"
	MainPercent     int         `json:"main_percent"`
	MaterialPercent int         `json:"material_percent"`
	FixedRewards    []BoxReward `json:"fixed_rewards"`
	MainRewards     []BoxReward `json:"main_rewards"`
	MaterialRewards []BoxReward `json:"material_rewards"`
	DuplicatePolicy string      `json:"duplicate_policy"` // e.g. "reject_owned_unique_main"
	NativeType      int         `json:"nativeType"`       // 20=gift, 27=egg
	Container       int         `json:"container"`
}

// RewardDef describes a reward template from the catalog.
type RewardDef struct {
	Key       string `json:"key"`
	Kind      string `json:"kind"` // "item", "tank"
	ID        uint32 `json:"id"`
	Category  string `json:"category"`
	Name      string `json:"name"`
	Container int    `json:"container"`
	StackMax  int    `json:"stack_max"`
	Unique    bool   `json:"unique"`
}

// GrantedReward represents a single granted reward from opening a box/present or sign-in.
type GrantedReward struct {
	Kind     string // "item", "tank", "currency"
	ID       uint32 // template ID for items/tanks
	CurrName string // "cash" (Xu), "gift" (Xu khóa), "silver"/"golden" (Bạc)
	Quantity int32
}

// CurrencyGrant defines what currency a consumable item gives per unit.
type CurrencyGrant struct {
	Cash   int32
	Golden int32 // xu khóa (Store.Golden, SettleAwardInfo.Gift)
	Silver int32 // bạc (Store.Silver, SettleAwardInfo.Golden)
}

// PresentEntry represents one reward row from bag.json "presents".
// Format in bag.json: [giveType, reuseA, count]
//   giveType 1 = item/pet/skin (reuseA = itemID)
//   giveType 2 = currency (reuseA: 1=cash/xu, 2=silver/bạc, 3=gift/xu khóa)
//   giveType 3 = tank (reuseA = tankID)
type PresentEntry struct {
	GiveType int
	ReuseA   uint32
	Count    int32
}

// SignInCatalog holds daily, milestone, and VIP sign-in rewards loaded from events.json.
type SignInCatalog struct {
	Week    [7][]GrantedReward         // index 0=Sun..6=Sat
	Marks   map[uint32][]GrantedReward // milestone days (5, 12, 21) → rewards
	VipGift [][]GrantedReward          // index (vipLevel-1) → rewards
}

// ItemCatalog holds box definitions, present definitions, container types, and sign-in rewards.
type ItemCatalog struct {
	Boxes          map[uint32]*BoxDef        // itemId → box definition (normal_shop_catalog.json)
	Rewards        map[string]*RewardDef     // "item:3000148" → reward info
	Presents       map[uint32][]PresentEntry // itemId → present rewards (bag.json "presents")
	ItemContainers map[uint32]uint8          // itemId → container type (bag.json "items" row[5])
	ItemTypes      map[uint32]int            // itemId → item type (bag.json "items" row[4])
	ItemReuse      map[uint32]uint32         // itemId → reuse/requirement ID (bag.json "items" row[9])
	SignIn         SignInCatalog             // sign-in rewards (events.json)
}

// catalogJSON is the top-level structure of normal_shop_catalog.json.
type catalogJSON struct {
	Boxes   map[string]json.RawMessage `json:"boxes"`
	Rewards map[string]json.RawMessage `json:"rewards"`
}

// NewItemCatalog creates an empty catalog (all item/gift data loaded from JSON config files).
func NewItemCatalog() *ItemCatalog {
	return &ItemCatalog{
		Boxes:          make(map[uint32]*BoxDef),
		Rewards:        make(map[string]*RewardDef),
		Presents:       make(map[uint32][]PresentEntry),
		ItemContainers: make(map[uint32]uint8),
		ItemTypes:      make(map[uint32]int),
		ItemReuse:      make(map[uint32]uint32),
		SignIn: SignInCatalog{
			Marks: make(map[uint32][]GrantedReward),
		},
	}
}

// LoadCatalog loads box definitions from normal_shop_catalog.json.
func (ic *ItemCatalog) LoadCatalog(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read catalog: %w", err)
	}

	var cat catalogJSON
	if err := json.Unmarshal(data, &cat); err != nil {
		return fmt.Errorf("parse catalog: %w", err)
	}

	// Parse boxes
	for _, raw := range cat.Boxes {
		var box BoxDef
		if err := json.Unmarshal(raw, &box); err != nil {
			log.Printf("[catalog] skip bad box: %v", err)
			continue
		}
		ic.Boxes[box.ItemID] = &box
	}

	// Parse rewards
	for key, raw := range cat.Rewards {
		var rew RewardDef
		if err := json.Unmarshal(raw, &rew); err != nil {
			log.Printf("[catalog] skip bad reward %s: %v", key, err)
			continue
		}
		ic.Rewards[key] = &rew
	}

	log.Printf("[catalog] loaded %d boxes, %d reward defs", len(ic.Boxes), len(ic.Rewards))
	return nil
}

// LoadBagJSON loads "presents" (725+ item gift definitions) and "items" container types
// from the Godot client asset file (godot/a/l/bag.json).
func (ic *ItemCatalog) LoadBagJSON(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read bag.json: %w", err)
	}

	var raw struct {
		Presents map[string][][]int64           `json:"presents"`
		Items    map[string][]json.RawMessage   `json:"items"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return fmt.Errorf("parse bag.json: %w", err)
	}

	for idStr, entries := range raw.Presents {
		id, err := strconv.ParseUint(idStr, 10, 32)
		if err != nil {
			continue
		}
		var list []PresentEntry
		for _, e := range entries {
			if len(e) < 3 {
				continue
			}
			list = append(list, PresentEntry{
				GiveType: int(e[0]),
				ReuseA:   uint32(e[1]),
				Count:    int32(e[2]),
			})
		}
		if len(list) > 0 {
			ic.Presents[uint32(id)] = list
		}
	}

	// row[4] = item type (46=tank card, 20=gift, 27=drop...), row[5] = container type, row[9] = reuse ID
	for idStr, row := range raw.Items {
		if len(row) <= 5 {
			continue
		}
		id, err := strconv.ParseUint(idStr, 10, 32)
		if err != nil {
			continue
		}
		tid := uint32(id)
		var itemType int
		if err := json.Unmarshal(row[4], &itemType); err == nil {
			ic.ItemTypes[tid] = itemType
		}
		var cont int
		if err := json.Unmarshal(row[5], &cont); err == nil && cont > 0 {
			ic.ItemContainers[tid] = uint8(cont)
		}
		if len(row) > 9 {
			var reuse uint32
			if err := json.Unmarshal(row[9], &reuse); err == nil && reuse > 0 {
				ic.ItemReuse[tid] = reuse
			}
		}
	}

	log.Printf("[catalog] loaded %d presents, %d item containers from bag.json", len(ic.Presents), len(ic.ItemContainers))
	return nil
}

// GetTankCardReward returns the TankID if templateID is a tank card (type 46) with valid reuse TankID.
func (ic *ItemCatalog) GetTankCardReward(templateID uint32) (uint32, bool) {
	if ic.ItemTypes[templateID] == 46 {
		if tankID := ic.ItemReuse[templateID]; tankID > 0 {
			return tankID, true
		}
	}
	return 0, false
}

// parseEventRewards converts events.json reward tuples ([itemID, count] or [0, coinIdx, count])
// into []GrantedReward.
// In events.gd: COINS = ["Xu", "Xu Khóa", "Bạc"] → 0=cash, 1=gift (xu khóa), 2=silver (bạc).
func parseEventRewards(tuples [][]int64) []GrantedReward {
	var out []GrantedReward
	for _, r := range tuples {
		if len(r) < 2 {
			continue
		}
		if r[0] == 0 && len(r) >= 3 {
			currName := "cash"
			switch r[1] {
			case 0:
				currName = "cash"
			case 1:
				currName = "gift"
			case 2:
				currName = "silver"
			}
			out = append(out, GrantedReward{
				Kind:     "currency",
				CurrName: currName,
				Quantity: int32(r[2]),
			})
		} else if r[0] > 0 {
			out = append(out, GrantedReward{
				Kind:     "item",
				ID:       uint32(r[0]),
				Quantity: int32(r[1]),
			})
		}
	}
	return out
}

// LoadEventsJSON loads daily/milestone/VIP sign-in rewards from godot/a/l/events.json.
func (ic *ItemCatalog) LoadEventsJSON(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read events.json: %w", err)
	}

	var raw struct {
		Week    [][][]int64         `json:"week"`
		Marks   [][]json.RawMessage `json:"marks"`
		VipGift [][][]int64         `json:"vip_gift"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return fmt.Errorf("parse events.json: %w", err)
	}

	for i := 0; i < len(raw.Week) && i < 7; i++ {
		ic.SignIn.Week[i] = parseEventRewards(raw.Week[i])
	}

	for _, m := range raw.Marks {
		if len(m) < 2 {
			continue
		}
		var days uint32
		var tuples [][]int64
		if err := json.Unmarshal(m[0], &days); err != nil {
			continue
		}
		if err := json.Unmarshal(m[1], &tuples); err != nil {
			continue
		}
		ic.SignIn.Marks[days] = parseEventRewards(tuples)
	}

	ic.SignIn.VipGift = make([][]GrantedReward, len(raw.VipGift))
	for i, vg := range raw.VipGift {
		ic.SignIn.VipGift[i] = parseEventRewards(vg)
	}

	log.Printf("[catalog] loaded sign-in rewards from events.json (marks=%d, vip_levels=%d)", len(ic.SignIn.Marks), len(ic.SignIn.VipGift))
	return nil
}

// IsPresent returns true if templateID is defined in bag.json "presents".
func (ic *ItemCatalog) IsPresent(templateID uint32) bool {
	_, ok := ic.Presents[templateID]
	return ok
}

// OpenPresent expands a bag.json present template into GrantedReward entries (multiplied by count).
func (ic *ItemCatalog) OpenPresent(templateID uint32, count int32) ([]GrantedReward, error) {
	entries, ok := ic.Presents[templateID]
	if !ok {
		return nil, fmt.Errorf("unknown present template %d", templateID)
	}
	if count <= 0 {
		count = 1
	}

	var granted []GrantedReward
	for _, e := range entries {
		switch e.GiveType {
		case 1: // item / pet / skin
			granted = append(granted, GrantedReward{
				Kind:     "item",
				ID:       e.ReuseA,
				Quantity: e.Count * count,
			})
		case 2: // currency: 1=cash (xu), 2=silver (bạc), 3=gift (xu khóa)
			currName := "silver"
			switch e.ReuseA {
			case 1:
				currName = "cash"
			case 2:
				currName = "silver"
			case 3:
				currName = "gift"
			}
			granted = append(granted, GrantedReward{
				Kind:     "currency",
				CurrName: currName,
				Quantity: e.Count * count,
			})
		case 3: // tank
			granted = append(granted, GrantedReward{
				Kind:     "tank",
				ID:       e.ReuseA,
				Quantity: 1,
			})
		}
	}
	return granted, nil
}

// GetSignInDailyRewards returns the daily sign-in rewards for a weekday (0=Sunday..6=Saturday).
func (ic *ItemCatalog) GetSignInDailyRewards(weekday int) []GrantedReward {
	if weekday < 0 || weekday >= 7 {
		return nil
	}
	return ic.SignIn.Week[weekday]
}

// GetSignInMarkRewards returns the milestone sign-in rewards for days (5, 12, 21).
func (ic *ItemCatalog) GetSignInMarkRewards(days uint32) []GrantedReward {
	return ic.SignIn.Marks[days]
}

// GetSignInVipRewards returns the VIP daily sign-in rewards for vipLevel (1-based).
func (ic *ItemCatalog) GetSignInVipRewards(vipLevel uint8) []GrantedReward {
	idx := int(vipLevel) - 1
	if idx < 0 {
		idx = 0
	}
	if idx >= len(ic.SignIn.VipGift) {
		return nil
	}
	return ic.SignIn.VipGift[idx]
}

// IsBox returns true if templateID is a known box (gift/egg).
func (ic *ItemCatalog) IsBox(templateID uint32) bool {
	_, ok := ic.Boxes[templateID]
	return ok
}

// containerCapacity returns max slot count per container (matches Python mail_rewards.CAPACITIES).
func containerCapacity(contType uint8) int {
	switch contType {
	case 2:
		return 45
	case 3, 5:
		return 135
	case 4, 10:
		return 100
	case 6:
		return 512
	case 7, 9:
		return 80
	default:
		return 100
	}
}

func rewardIDUint32(v interface{}) uint32 {
	switch id := v.(type) {
	case float64:
		return uint32(id)
	case int:
		return uint32(id)
	case uint32:
		return id
	}
	return 0
}

// ValidateCanOpenBox checks Python shop_boxes.plans invariants BEFORE consuming/rolling:
//  1. Rejects if character already owns a permanent unique main prize (reject_owned_unique_main).
//  2. Rejects if any possible reward's target bag container has no space (bag_full).
func (ic *ItemCatalog) ValidateCanOpenBox(s *Store, charID uint32, templateID uint32) error {
	box, ok := ic.Boxes[templateID]
	if !ok {
		return fmt.Errorf("unknown box template %d", templateID)
	}

	s.mu.RLock()
	defer s.mu.RUnlock()

	c := s.characters[charID]
	if c == nil {
		return fmt.Errorf("character %d not found", charID)
	}

	// 1. Check duplicate unique main prize
	if box.DuplicatePolicy == "reject_owned_unique_main" || box.Mode == "random" {
		for _, r := range box.MainRewards {
			id := rewardIDUint32(r.ID)
			if id == 0 {
				continue
			}
			switch r.Kind {
			case "tank":
				for _, t := range c.Tanks {
					if t.TankID == id && t.ExistTime == 0 {
						return fmt.Errorf("already_owned: tank %d", id)
					}
				}
			case "item":
				isUnique := false
				if rew, ok := ic.Rewards[fmt.Sprintf("item:%d", id)]; ok && rew.Unique {
					isUnique = true
				}
				cont := ic.GetRewardContainerType(id)
				if cont == 4 || cont == 5 || cont == 6 || cont == 7 || cont == 9 {
					isUnique = true
				}
				if isUnique {
					for _, it := range c.Items {
						if it.TemplateID == id && it.Count > 0 && it.LifeTime == 0 {
							return fmt.Errorf("already_owned: item %d", id)
						}
					}
				}
			}
		}
	}

	// 2. Check target bag container capacity across all possible branches
	var allPossible []BoxReward
	allPossible = append(allPossible, box.FixedRewards...)
	allPossible = append(allPossible, box.MainRewards...)
	allPossible = append(allPossible, box.MaterialRewards...)

	for _, r := range allPossible {
		if r.Kind != "item" {
			continue
		}
		id := rewardIDUint32(r.ID)
		if id == 0 {
			continue
		}
		cont := ic.GetRewardContainerType(id)

		// Check if stackable onto an existing slot
		canStack := false
		usedSlots := 0
		for _, it := range c.Items {
			if it.ContType == cont {
				usedSlots++
				if it.TemplateID == id {
					canStack = true
				}
			}
		}
		if !canStack && usedSlots >= containerCapacity(cont) {
			return fmt.Errorf("bag_full: container %d (%d/%d)", cont, usedSlots, containerCapacity(cont))
		}
	}

	return nil
}

// OpenBox opens a gift box and returns the granted rewards.
// Uses crypto/rand for fair randomness (matching Python's secrets.randbelow).
func (ic *ItemCatalog) OpenBox(templateID uint32) ([]GrantedReward, error) {
	box, ok := ic.Boxes[templateID]
	if !ok {
		return nil, fmt.Errorf("unknown box template %d", templateID)
	}

	var rewards []BoxReward

	switch box.Mode {
	case "fixed":
		rewards = box.FixedRewards

	case "random":
		// 10% chance for main reward, 90% for material
		n, err := rand.Int(rand.Reader, big.NewInt(100))
		if err != nil {
			return nil, fmt.Errorf("random error: %w", err)
		}
		if n.Int64() < int64(box.MainPercent) {
			// Main prize — pick one random main reward
			if len(box.MainRewards) == 1 {
				rewards = box.MainRewards
			} else if len(box.MainRewards) > 1 {
				idx, _ := rand.Int(rand.Reader, big.NewInt(int64(len(box.MainRewards))))
				rewards = []BoxReward{box.MainRewards[idx.Int64()]}
			}
		} else {
			// Material prize — pick one random material reward (matches Python shop_boxes.select)
			if len(box.MaterialRewards) == 1 {
				rewards = box.MaterialRewards
			} else if len(box.MaterialRewards) > 1 {
				idx, _ := rand.Int(rand.Reader, big.NewInt(int64(len(box.MaterialRewards))))
				rewards = []BoxReward{box.MaterialRewards[idx.Int64()]}
			}
		}

	default:
		return nil, fmt.Errorf("unknown box mode %q for %d", box.Mode, templateID)
	}

	// Convert BoxReward → GrantedReward
	var granted []GrantedReward
	for _, r := range rewards {
		gr := GrantedReward{
			Kind:     r.Kind,
			Quantity: r.Quantity,
		}
		switch r.Kind {
		case "item", "tank":
			switch id := r.ID.(type) {
			case float64:
				gr.ID = uint32(id)
			case int:
				gr.ID = uint32(id)
			}
		case "currency":
			if name, ok := r.ID.(string); ok {
				gr.CurrName = name
			}
		}
		granted = append(granted, gr)
	}

	return granted, nil
}

// GetRewardContainerType returns the container type for a reward item template ID.
// Checks bag.json "items" row[5], then normal_shop_catalog.json rewards, then heuristics.
func (ic *ItemCatalog) GetRewardContainerType(templateID uint32) uint8 {
	if cont, ok := ic.ItemContainers[templateID]; ok && cont > 0 {
		return cont
	}
	key := fmt.Sprintf("item:%d", templateID)
	if rew, ok := ic.Rewards[key]; ok && rew.Container > 0 {
		return uint8(rew.Container)
	}
	// Default containers by ID range heuristics
	if templateID >= 2000000 && templateID < 3000000 {
		return 2 // props / items
	}
	if templateID >= 3000000 && templateID < 4000000 {
		return 3 // materials
	}
	if templateID >= 4400000 && templateID < 4500000 {
		return 5 // helpers (trợ thủ)
	}
	return 3 // default: materials
}

// ============================================================================
// Store methods for granting box rewards
// ============================================================================

// GrantBoxRewards processes granted rewards: adds items/tanks/currency to character.
// Returns the list of items actually added (for 1102 notifications).
func (s *Store) GrantBoxRewards(charID uint32, rewards []GrantedReward, catalog *ItemCatalog) []PlayerItem {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return nil
	}

	var addedItems []PlayerItem

	for _, r := range rewards {
		switch r.Kind {
		case "currency":
			switch r.CurrName {
			case "cash":
				c.Cash += r.Quantity
			case "gift":
				c.Golden += r.Quantity // xu khóa
			case "silver", "golden":
				c.Silver += r.Quantity // bạc ("golden" in Python normal_shop_catalog.json = Bạc)
			}

		case "item":
			contType := catalog.GetRewardContainerType(r.ID)
			item := s.addItemLocked(c, contType, r.ID, r.Quantity)
			if item != nil {
				addedItems = append(addedItems, *item)
			}

		case "tank":
			s.addTankLocked(c, r.ID)
		}
	}

	return addedItems
}

// addItemLocked adds an item to character inventory (must hold s.mu).
func (s *Store) addItemLocked(c *Character, contType uint8, templateID uint32, count int32) *PlayerItem {
	// Check if stackable: find existing item with same template
	for i := range c.Items {
		if c.Items[i].ContType == contType && c.Items[i].TemplateID == templateID {
			c.Items[i].Count += count
			return &c.Items[i]
		}
	}

	// Find next available slot
	var maxSlot int16 = -1
	for _, it := range c.Items {
		if it.ContType == contType && it.SlotNo > maxSlot {
			maxSlot = it.SlotNo
		}
	}

	newItem := PlayerItem{
		ItemUuid:   generateUUID(),
		ContType:   contType,
		SlotNo:     maxSlot + 1,
		TemplateID: templateID,
		Count:      count,
		CreateTime: uint32(time.Now().Unix()),
	}
	c.Items = append(c.Items, newItem)
	return &newItem
}

// addTankLocked adds a tank to character (must hold s.mu).
func (s *Store) addTankLocked(c *Character, tankTemplateID uint32) {
	// Check if already owned
	for _, t := range c.Tanks {
		if t.TankID == tankTemplateID {
			return // already owned
		}
	}

	newTank := PlayerTank{
		TankUuid:  generateUUID(),
		TankID:    tankTemplateID,
		TankLevel: 1,
		ContType:  1,
		OwnTime:   uint32(time.Now().Unix()),
	}
	c.Tanks = append(c.Tanks, newTank)
}

// RemoveItem removes count units of an item at a specific slot. Returns the item UUID for notifications.
func (s *Store) RemoveItem(charID uint32, contType uint8, slotNo int16, count int32) (removedUUID string, remainingCount int32) {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return "", 0
	}

	for i := range c.Items {
		if c.Items[i].ContType == contType && c.Items[i].SlotNo == slotNo {
			removedUUID = c.Items[i].ItemUuid
			c.Items[i].Count -= count
			if c.Items[i].Count <= 0 {
				c.Items = append(c.Items[:i], c.Items[i+1:]...)
				return removedUUID, 0
			}
			return removedUUID, c.Items[i].Count
		}
	}
	return "", 0
}

// generateUUID is defined in store.go — reuse it via the same package.
