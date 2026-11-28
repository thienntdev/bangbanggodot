package game

import (
	"sync"
)

// ============================================================================
// PvE Progression & Military Rank System
// Client expects:
//   C→S 308: request solo PvE info (empty)
//   C→S 304: select tutor map (u32 mapId)
//   C→S 307: sweep solo map (u32 cityId, u32 count)
//   C→S 306: reset map enter count (u32 mapId)
//   C→S 558: request PvE record (u32 mapId)
//   S→C 1303: city info init (array CITY_INFO)
//   S→C 1304: update city info (array CITY_INFO)
//   S→C 1300: chapter scenes (u32 chapterId, array CHAPTER_SCENE) — simplified
//   S→C 1305: sweep solo award (array SettleAwardInfo)
//   S→C 1516: PvE record (OnePveRecord + u8 byte)
//   S→C 85: update char data (u8 type=27, u32 militaryStar, utf8 "")
// ============================================================================

// CityInfo is the wire-level PvE city record.
// 18 bytes: u32 cityId, u32 value, u8 evalEasy, u8 evalDiff, u32 diffPass, u32 resetTime
type CityInfo struct {
	CityID    uint32
	Value     uint32 // bitmask flags
	EvalEasy  uint8  // normal grade
	EvalDiff  uint8  // hard grade
	DiffPass  uint32 // hard passes today
	ResetTime uint32 // daily reset count
}

// CityFlag bitmask constants.
const (
	CityFlagEnable      uint32 = 1
	CityFlagLevel       uint32 = 2
	CityFlagQuest       uint32 = 4
	CityFlagPreCity     uint32 = 8
	CityFlagCommon      uint32 = 16  // permanent normal clear
	CityFlagHero        uint32 = 32  // permanent hard clear
	CityFlagCommonToday uint32 = 64  // cleared today normal
	CityFlagHeroToday   uint32 = 128 // cleared today hard
)

// PlayerPveData stores PvE data for one player.
type PlayerPveData struct {
	Cities       map[uint32]*CityInfo
	MilitaryStar uint32
}

// PveManager manages PvE data for all players.
type PveManager struct {
	mu      sync.RWMutex
	players map[uint32]*PlayerPveData
}

func NewPveManager() *PveManager {
	return &PveManager{
		players: make(map[uint32]*PlayerPveData),
	}
}

// Default PvE cities (map 201 = tutorial, some starter cities)
var defaultCities = []CityInfo{
	{CityID: 201, Value: CityFlagEnable | CityFlagLevel | CityFlagQuest | CityFlagPreCity | CityFlagCommon, EvalEasy: 3},
	{CityID: 202, Value: CityFlagEnable | CityFlagLevel | CityFlagQuest | CityFlagPreCity},
	{CityID: 203, Value: CityFlagEnable | CityFlagLevel},
	{CityID: 204, Value: CityFlagEnable},
	{CityID: 205, Value: CityFlagEnable},
}

func (m *PveManager) getOrCreate(charID uint32) *PlayerPveData {
	data, ok := m.players[charID]
	if !ok {
		data = &PlayerPveData{
			Cities: make(map[uint32]*CityInfo),
		}
		for _, c := range defaultCities {
			city := c // copy
			data.Cities[c.CityID] = &city
		}
		m.players[charID] = data
	}
	return data
}

// GetCities returns all PvE cities for a player.
func (m *PveManager) GetCities(charID uint32) []CityInfo {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	result := make([]CityInfo, 0, len(data.Cities))
	for _, c := range data.Cities {
		result = append(result, *c)
	}
	return result
}

// GetMilitaryStar returns military star count for a player.
func (m *PveManager) GetMilitaryStar(charID uint32) uint32 {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	return data.MilitaryStar
}

// SetMilitaryStar sets military star count for a player.
func (m *PveManager) SetMilitaryStar(charID uint32, stars uint32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	data.MilitaryStar = stars
}
