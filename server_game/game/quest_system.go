package game

import (
	"log"
	"sync"
	"time"
)

// ============================================================================
// Quest & Stage System — built from scratch based on Godot client protocol.
// Client expects:
//   C→S 280: quest complete (u32 questID, u32 choice)
//   C→S 281: quest open UI (u8 uiID)
//   C→S 285: rand quest switch (u32 questID)
//   S→C 1250: quest list (u16 count, [count × 28B quest], u32 kind)
//   S→C 1251: quest update (28B quest)
//   S→C 1252: quest remove (u16 count, [count × u32 questID])
//   S→C 1254: quest failed (u32 questID)
//   C→S 74: stage reap (u32 stageID, u8 show)
//   S→C 1306: stage info (u32 stage, u32 reward, u32 reaped, u32 next, u32 flag, u32 level, u32 value)
//   S→C 1307: stage reaped result (u32 result, u32 stageID)
//   S→C 1308: stage cleared (u32 stageID, [u32 extra])
//   S→C 1309: stage progress (u32 type, u16 count, [count × u32 value], u16 topCount, [topCount × u32 value])
// ============================================================================

// QuestState values used by the client:
//   0 = not started
//   1 = accepted (tracking)
//   2 = in progress
//   3 = completed (ready to claim)
//   4 = rewarded (done)
const (
	QuestStateNone       uint32 = 0
	QuestStateAccepted   uint32 = 1
	QuestStateInProgress uint32 = 2
	QuestStateCompleted  uint32 = 3
	QuestStateRewarded   uint32 = 4
)

// QuestEntry represents one quest tracked by the server.
// Client receives 28 bytes: questID(u32) + state(u32) + count(u32) + f3(u32) + f4(u32) + f5(u32) + f6(u32)
type QuestEntry struct {
	QuestID uint32
	State   uint32 // QuestState*
	Count   uint32 // progress counter
	Field3  uint32 // extra field
	Field4  uint32
	Field5  uint32
	Field6  uint32
}

// StageEntry represents a stage/event milestone tracked by the server.
type StageEntry struct {
	StageID uint32
	Reward  uint32 // 0=not ready, 1=ready to reap
	Reaped  uint32 // times reaped
	Next    uint32 // next stage ID in sequence
	Flag    uint32
	Level   uint32
	Value   uint32 // progress value
}

// QuestManager manages quests and stages per player.
type QuestManager struct {
	mu     sync.RWMutex
	quests map[uint32]map[uint32]*QuestEntry // charID -> questID -> entry
	stages map[uint32]map[uint32]*StageEntry // charID -> stageID -> entry
}

func NewQuestManager() *QuestManager {
	return &QuestManager{
		quests: make(map[uint32]map[uint32]*QuestEntry),
		stages: make(map[uint32]map[uint32]*StageEntry),
	}
}

// InitPlayer sets up initial quests for a player (called on login).
func (qm *QuestManager) InitPlayer(charID uint32) {
	qm.mu.Lock()
	defer qm.mu.Unlock()

	if _, ok := qm.quests[charID]; !ok {
		qm.quests[charID] = make(map[uint32]*QuestEntry)
	}
	if _, ok := qm.stages[charID]; !ok {
		qm.stages[charID] = make(map[uint32]*StageEntry)
	}

	// Generate sample daily quests if none exist
	pq := qm.quests[charID]
	if len(pq) == 0 {
		dailyQuests := []struct {
			ID    uint32
			State uint32
			Need  uint32
		}{
			// Quest types from client: 11=daily activity, 12=daily arena, etc.
			{10001, QuestStateInProgress, 0}, // "Đánh 1 trận" (play 1 match)
			{10002, QuestStateInProgress, 0}, // "Thắng 1 trận" (win 1 match)
			{10003, QuestStateInProgress, 0}, // "Tiêu diệt 5 địch" (kill 5 enemies)
			{10004, QuestStateInProgress, 0}, // "Gây 10000 dame" (deal 10000 damage)
			{10005, QuestStateInProgress, 0}, // "Dùng kỹ năng 3 lần" (use skill 3 times)
		}
		for _, dq := range dailyQuests {
			pq[dq.ID] = &QuestEntry{
				QuestID: dq.ID,
				State:   dq.State,
				Count:   dq.Need,
			}
		}
	}

	// Set up daily stage (fizz points milestones)
	ps := qm.stages[charID]
	if len(ps) == 0 {
		// Stage 700-706 = daily fizz reward milestones (from client code)
		for i := uint32(700); i <= 706; i++ {
			if _, ok := ps[i]; !ok {
				ps[i] = &StageEntry{
					StageID: i,
					Reward:  0,
					Next:    i + 1,
					Value:   0,
				}
				break // only first unclaimed stage is active
			}
		}
	}
}

// GetQuests returns all quests for a player.
func (qm *QuestManager) GetQuests(charID uint32) []*QuestEntry {
	qm.mu.RLock()
	defer qm.mu.RUnlock()

	pq := qm.quests[charID]
	if pq == nil {
		return nil
	}
	result := make([]*QuestEntry, 0, len(pq))
	for _, q := range pq {
		result = append(result, q)
	}
	return result
}

// GetStages returns all stages for a player.
func (qm *QuestManager) GetStages(charID uint32) []*StageEntry {
	qm.mu.RLock()
	defer qm.mu.RUnlock()

	ps := qm.stages[charID]
	if ps == nil {
		return nil
	}
	result := make([]*StageEntry, 0, len(ps))
	for _, s := range ps {
		result = append(result, s)
	}
	return result
}

// CompleteQuest claims a completed quest's reward. Returns the entry if successful.
func (qm *QuestManager) CompleteQuest(charID, questID, choice uint32) *QuestEntry {
	qm.mu.Lock()
	defer qm.mu.Unlock()

	pq := qm.quests[charID]
	if pq == nil {
		return nil
	}
	q, ok := pq[questID]
	if !ok || q.State != QuestStateCompleted {
		return nil
	}

	q.State = QuestStateRewarded
	log.Printf("[quest] char %d completed quest %d (choice=%d)", charID, questID, choice)
	return q
}

// RemoveQuest removes a quest from tracking.
func (qm *QuestManager) RemoveQuest(charID, questID uint32) {
	qm.mu.Lock()
	defer qm.mu.Unlock()

	if pq := qm.quests[charID]; pq != nil {
		delete(pq, questID)
	}
}

// NotifyOpenUI is called when client sends quest_open_ui (msg 281).
// Checks quests whose check_type == CKT_OPEN_UI (27) and check_id matches.
func (qm *QuestManager) NotifyOpenUI(charID uint32, uiID uint8) []*QuestEntry {
	qm.mu.Lock()
	defer qm.mu.Unlock()

	pq := qm.quests[charID]
	if pq == nil {
		return nil
	}

	var updated []*QuestEntry
	for _, q := range pq {
		if q.State == QuestStateInProgress {
			// Quest check type "open UI" triggers completion
			q.Count++
			if q.Count >= 1 {
				q.State = QuestStateCompleted
			}
			updated = append(updated, q)
		}
	}
	return updated
}

// UpdateBattleProgress updates quest progress from battle events.
// checkType: "kills"=kills, "damage"=damage dealt, "matches"=matches played, "wins"=wins
func (qm *QuestManager) UpdateBattleProgress(charID uint32, kills, damage, matchesPlayed, wins uint32) []*QuestEntry {
	qm.mu.Lock()
	defer qm.mu.Unlock()

	pq := qm.quests[charID]
	if pq == nil {
		return nil
	}

	var updated []*QuestEntry
	for _, q := range pq {
		if q.State != QuestStateInProgress {
			continue
		}
		switch q.QuestID {
		case 10001: // play 1 match
			q.Count += matchesPlayed
			if q.Count >= 1 {
				q.State = QuestStateCompleted
			}
			updated = append(updated, q)
		case 10002: // win 1 match
			q.Count += wins
			if q.Count >= 1 {
				q.State = QuestStateCompleted
			}
			updated = append(updated, q)
		case 10003: // kill 5 enemies
			q.Count += kills
			if q.Count >= 5 {
				q.State = QuestStateCompleted
			}
			updated = append(updated, q)
		case 10004: // deal 10000 damage
			q.Count += damage
			if q.Count >= 10000 {
				q.State = QuestStateCompleted
			}
			updated = append(updated, q)
		case 10005: // use skill 3 times
			// Updated from skill usage, not here
		}
	}
	return updated
}

// ReapStage claims a stage milestone reward.
func (qm *QuestManager) ReapStage(charID, stageID uint32) (result uint32, ok bool) {
	qm.mu.Lock()
	defer qm.mu.Unlock()

	ps := qm.stages[charID]
	if ps == nil {
		return 0, false
	}
	s, exists := ps[stageID]
	if !exists || s.Reward != 1 {
		return 0, false
	}

	s.Reaped++
	s.Reward = 0 // already claimed
	log.Printf("[quest] char %d reaped stage %d", charID, stageID)
	return 0, true // result=0 means success
}

// ============================================================================
// Sign-in (Điểm danh) System
// Client expects:
//   C→S 360: sign today (empty body)
//   C→S 361: sign mark claim (u32 days)
//   C→S 362: VIP sign (empty body)
//   S→C 1400: sign info (u32 flag, u32 vip_flag, u32 year, u32 month, u32 day, u32 count, u32 stage)
// ============================================================================

// SignInData stores daily sign-in state for a player.
type SignInData struct {
	Flag    uint32 // bitmask of signed-in days (bit N = day N signed)
	VipFlag uint32 // bitmask of VIP sign-in days
	Year    uint32
	Month   uint32
	Day     uint32 // today (1-based)
	Count   uint32 // total sign-in count this month
	Stage   uint32 // last claimed milestone stage
}

// SignInManager handles daily check-in.
type SignInManager struct {
	mu   sync.RWMutex
	data map[uint32]*SignInData // charID -> sign-in data
}

func NewSignInManager() *SignInManager {
	return &SignInManager{
		data: make(map[uint32]*SignInData),
	}
}

// GetSignIn returns sign-in data for a player, initializing if needed.
func (sm *SignInManager) GetSignIn(charID uint32) *SignInData {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	now := time.Now()
	d := sm.data[charID]
	if d == nil || d.Year != uint32(now.Year()) || d.Month != uint32(now.Month()) {
		// New month or first time — reset
		d = &SignInData{
			Year:  uint32(now.Year()),
			Month: uint32(now.Month()),
			Day:   uint32(now.Day()),
		}
		sm.data[charID] = d
	} else {
		d.Day = uint32(now.Day()) // always update today
	}
	return d
}

// SignToday performs today's sign-in. Returns updated data and whether it was new.
func (sm *SignInManager) SignToday(charID uint32) (*SignInData, bool) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	now := time.Now()
	d := sm.data[charID]
	if d == nil || d.Year != uint32(now.Year()) || d.Month != uint32(now.Month()) {
		d = &SignInData{
			Year:  uint32(now.Year()),
			Month: uint32(now.Month()),
			Day:   uint32(now.Day()),
		}
		sm.data[charID] = d
	}
	d.Day = uint32(now.Day())

	dayBit := uint32(1) << d.Day
	if d.Flag&dayBit != 0 {
		// Already signed today
		return d, false
	}

	d.Flag |= dayBit
	d.Count++
	log.Printf("[signin] char %d signed day %d (count=%d)", charID, d.Day, d.Count)
	return d, true
}

// SignVip performs VIP sign-in for today.
func (sm *SignInManager) SignVip(charID uint32) (*SignInData, bool) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	now := time.Now()
	d := sm.data[charID]
	if d == nil || d.Year != uint32(now.Year()) || d.Month != uint32(now.Month()) {
		d = &SignInData{
			Year:  uint32(now.Year()),
			Month: uint32(now.Month()),
			Day:   uint32(now.Day()),
		}
		sm.data[charID] = d
	}
	d.Day = uint32(now.Day())

	dayBit := uint32(1) << d.Day
	if d.VipFlag&dayBit != 0 {
		return d, false
	}

	d.VipFlag |= dayBit
	log.Printf("[signin] char %d VIP signed day %d", charID, d.Day)
	return d, true
}

// ClaimMark claims a sign-in milestone reward.
func (sm *SignInManager) ClaimMark(charID, days uint32) (*SignInData, bool) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	d := sm.data[charID]
	if d == nil {
		return nil, false
	}

	if d.Count < days {
		return d, false // not enough sign-ins
	}

	if d.Stage >= days {
		return d, false // already claimed this milestone
	}

	d.Stage = days
	log.Printf("[signin] char %d claimed milestone %d days", charID, days)
	return d, true
}
