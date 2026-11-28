package game

import (
	"sync"
)

// ============================================================================
// Crystal (Tinh Thể) System — built from scratch based on Godot client protocol.
// Client expects:
//   C→S 423: request crystal scheme info (empty body)
//   C→S 424: save crystal scheme (124 bytes: u32 schemeId + 30 × u32 slot)
//   C→S 425: rename crystal scheme (u32 schemeId, utf8 name)
//   C→S 426: forge/sell crystals (u32 sell, u16 count, count × u32 itemId)
//   C→S 427: set current scheme for tank (u32 schemeId, utf8 tankUuid)
//   C→S 430: crystal make/gacha (u32 kind)
//   S→C 1454: crystal scheme info (array of 124-byte structs)
//   S→C 1455: crystal scheme names (array of {u32 id, utf8 name})
//   S→C 1457: rename result (u32 result)
//   S→C 1459: forge result (u32 itemId)
//   S→C 1461: crystal make free cooldown (u32 coolEndTime)
// ============================================================================

const (
	CrystalSlotsPerScheme = 30
	CrystalMaxSchemes     = 5
	CrystalSchemeBytes    = 4 + CrystalSlotsPerScheme*4 // 124 bytes
)

// CrystalScheme represents one crystal scheme (30 slots of item IDs).
type CrystalScheme struct {
	SchemeID uint32
	Slots    [CrystalSlotsPerScheme]uint32
}

// PlayerCrystalData stores all crystal data for one player.
type PlayerCrystalData struct {
	Schemes    map[uint32]*CrystalScheme // schemeID -> scheme
	Names      map[uint32]string         // schemeID -> name
	FreeAt     uint32                    // Unix timestamp when next free make is available
}

// CrystalManager manages crystal data for all players.
type CrystalManager struct {
	mu      sync.RWMutex
	players map[uint32]*PlayerCrystalData
}

func NewCrystalManager() *CrystalManager {
	return &CrystalManager{
		players: make(map[uint32]*PlayerCrystalData),
	}
}

func (m *CrystalManager) getOrCreate(charID uint32) *PlayerCrystalData {
	data, ok := m.players[charID]
	if !ok {
		data = &PlayerCrystalData{
			Schemes: map[uint32]*CrystalScheme{
				1: {SchemeID: 1},
			},
			Names: map[uint32]string{
				1: "Nhóm 1",
			},
			FreeAt: 0,
		}
		m.players[charID] = data
	}
	return data
}

// GetSchemes returns all crystal schemes for a player.
func (m *CrystalManager) GetSchemes(charID uint32) []*CrystalScheme {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	result := make([]*CrystalScheme, 0, len(data.Schemes))
	for _, s := range data.Schemes {
		result = append(result, s)
	}
	return result
}

// GetNames returns all crystal scheme names for a player.
func (m *CrystalManager) GetNames(charID uint32) map[uint32]string {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	out := make(map[uint32]string, len(data.Names))
	for k, v := range data.Names {
		out[k] = v
	}
	return out
}

// GetFreeAt returns the free make cooldown timestamp.
func (m *CrystalManager) GetFreeAt(charID uint32) uint32 {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	return data.FreeAt
}

// SaveScheme saves a crystal scheme's slots.
func (m *CrystalManager) SaveScheme(charID uint32, schemeID uint32, slots [CrystalSlotsPerScheme]uint32) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)

	if schemeID < 1 || schemeID > CrystalMaxSchemes {
		return false
	}
	scheme, ok := data.Schemes[schemeID]
	if !ok {
		return false
	}
	scheme.Slots = slots
	return true
}

// RenameScheme renames a crystal scheme. Returns true on success.
func (m *CrystalManager) RenameScheme(charID uint32, schemeID uint32, name string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)

	if _, ok := data.Schemes[schemeID]; !ok {
		return false
	}
	data.Names[schemeID] = name
	return true
}

// ForgeResult processes a crystal forge/sell request. Returns true on success.
func (m *CrystalManager) ForgeResult(charID uint32, sell bool, itemIDs []uint32) bool {
	// In a real implementation, we'd modify inventory.
	// For now, just accept the request.
	return len(itemIDs) > 0
}

// CrystalMake processes a crystal make/gacha request. Returns cooldown timestamp.
func (m *CrystalManager) CrystalMake(charID uint32, kind uint32) uint32 {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)

	// For free make (kind=2), set cooldown
	if kind == 2 {
		data.FreeAt = uint32(0) // no cooldown for now
	}
	return data.FreeAt
}
