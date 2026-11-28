package game

import (
	"sync"
	"time"

	"github.com/google/uuid"
)

// ============================================================================
// Talent System — built from scratch based on Godot client protocol.
// Client expects:
//   C→S 420: add talent page (utf8 pageName, u8 buyType)
//   C→S 421: save talent page (TALENT_PAGE struct)
//   C→S 422: op talent page  (u32 opType, utf8 pageUuid, utf8 tankUuid)
//   S→C 1450: update talent page (u32 opType, TALENT_PAGE)
//   S→C 1451: op talent page (u32 opType, utf8 pageUuid)
//   S→C 1452: talent info (array TALENT_PAGE, u32 totalPoint, u8 buyPageCount)
//   S→C 1453: talent total point (u32 totalPoint)
// ============================================================================

const (
	TalentMaxFreePages = 5
	TalentMaxBuyPages  = 10 // max purchased pages
	TalentMaxGrids     = 65535

	TalentOpAdd     uint32 = 1
	TalentOpSave    uint32 = 2
	TalentOpReset   uint32 = 3
	TalentOpDel     uint32 = 4
	TalentOpSetCur  uint32 = 5
	TalentOpAllPage uint32 = 6
	TalentOpCopy    uint32 = 7
)

// TalentGrid represents one talent node in a page.
type TalentGrid struct {
	TalentID uint32
	Level    uint16
}

// TalentPage represents a talent page.
type TalentPage struct {
	UUID       string
	Name       string
	Tree       []TalentGrid
	CreateTime uint32
}

// PlayerTalentData stores all talent data for one player.
type PlayerTalentData struct {
	Pages        []TalentPage
	TotalPoint   uint32
	BuyPageCount uint8
}

// TalentManager manages talent data for all players.
type TalentManager struct {
	mu      sync.RWMutex
	players map[uint32]*PlayerTalentData // charID -> data
}

func NewTalentManager() *TalentManager {
	return &TalentManager{
		players: make(map[uint32]*PlayerTalentData),
	}
}

func (m *TalentManager) getOrCreate(charID uint32) *PlayerTalentData {
	data, ok := m.players[charID]
	if !ok {
		// Initialize with one default page
		data = &PlayerTalentData{
			Pages: []TalentPage{
				{
					UUID:       uuid.New().String(),
					Name:       "Kỹ Thuật 1",
					Tree:       nil,
					CreateTime: uint32(time.Now().Unix()),
				},
			},
			TotalPoint:   30, // default talent points
			BuyPageCount: 0,
		}
		m.players[charID] = data
	}
	return data
}

// GetTalentInfo returns all talent data for a player.
func (m *TalentManager) GetTalentInfo(charID uint32) *PlayerTalentData {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.getOrCreate(charID)
}

// AddPage adds a new talent page. Returns the new page or nil if limit reached.
func (m *TalentManager) AddPage(charID uint32, name string, buyType uint8) *TalentPage {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)

	maxPages := TalentMaxFreePages + int(data.BuyPageCount)
	if len(data.Pages) >= maxPages {
		return nil
	}

	page := TalentPage{
		UUID:       uuid.New().String(),
		Name:       name,
		Tree:       nil,
		CreateTime: uint32(time.Now().Unix()),
	}
	data.Pages = append(data.Pages, page)
	return &data.Pages[len(data.Pages)-1]
}

// SavePage updates an existing talent page's tree and name.
func (m *TalentManager) SavePage(charID uint32, page TalentPage) *TalentPage {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)

	for i := range data.Pages {
		if data.Pages[i].UUID == page.UUID {
			data.Pages[i].Name = page.Name
			data.Pages[i].Tree = page.Tree
			return &data.Pages[i]
		}
	}
	return nil
}

// ResetPage clears the tree of a talent page.
func (m *TalentManager) ResetPage(charID uint32, pageUUID string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)

	for i := range data.Pages {
		if data.Pages[i].UUID == pageUUID {
			data.Pages[i].Tree = nil
			return true
		}
	}
	return false
}

// DeletePage removes a talent page. Returns false if page not found or is the last one.
func (m *TalentManager) DeletePage(charID uint32, pageUUID string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)

	if len(data.Pages) <= 1 {
		return false // can't delete last page
	}

	for i := range data.Pages {
		if data.Pages[i].UUID == pageUUID {
			data.Pages = append(data.Pages[:i], data.Pages[i+1:]...)
			return true
		}
	}
	return false
}
