package game

import "sync"

// Room represents an active game room.
type Room struct {
	ID       uint32
	Name     string
	Type     uint8  // room type (1=custom, 2=pvp, etc.)
	Mode     uint32 // game mode
	MapID    uint32
	Password uint32
	State    uint8 // 0=waiting, 1=playing
	MaxSlots uint32
	OwnerID  uint32 // char ID of room creator

	// Members tracks char IDs currently in the room.
	Members []uint32
	// MemberBriefs stores pre-encoded ROOM_CHAR_BRIEF for each member (keyed by charID).
	MemberBriefs map[uint32][]byte
	// MemberCamps stores camp (1=Camp A, 2=Camp B) for each member.
	MemberCamps map[uint32]uint8
	// MemberReady tracks ready state for each member (host is ready, guest defaults false).
	MemberReady map[uint32]bool
	// MemberPositions tracks current (X, Y) of members in battle.
	MemberPositions map[uint32]*MemberPos
	// NextBullet tracks next bullet ID.
	NextBullet uint32
	// LoadedMembers tracks which members reported 100% loaded.
	LoadedMembers map[uint32]bool
	// MemberSkills tracks skill templates [SkillE, SkillSpace, Passive, SkillR] for each member.
	MemberSkills map[uint32][4]uint32
	// BattleStarted indicates whether 1586 has been sent for this match.
	BattleStarted bool
}

// MemberPos represents a 2D coordinate in battle.
type MemberPos struct {
	X int16
	Y int16
}

// RoomManager holds all active rooms in memory.
type RoomManager struct {
	mu     sync.RWMutex
	rooms  map[uint32]*Room
	nextID uint32
}

// NewRoomManager creates a new room manager.
func NewRoomManager() *RoomManager {
	return &RoomManager{
		rooms:  make(map[uint32]*Room),
		nextID: 1001,
	}
}

// CreateRoom adds a new room and returns it.
func (m *RoomManager) CreateRoom(name string, roomType uint8, mode uint32, mapID uint32, password uint32, ownerID uint32, ownerBrief []byte) *Room {
	m.mu.Lock()
	defer m.mu.Unlock()

	id := m.nextID
	m.nextID++

	r := &Room{
		ID:              id,
		Name:            name,
		Type:            roomType,
		Mode:            mode,
		MapID:           mapID,
		Password:        password,
		State:           0,
		MaxSlots:        10,
		OwnerID:         ownerID,
		Members:         []uint32{ownerID},
		MemberBriefs:    map[uint32][]byte{ownerID: ownerBrief},
		MemberCamps:     map[uint32]uint8{ownerID: 1},
		MemberReady:     map[uint32]bool{ownerID: true},
		MemberPositions: make(map[uint32]*MemberPos),
		NextBullet:      1000,
		LoadedMembers:   make(map[uint32]bool),
	}
	m.rooms[id] = r
	return r
}

// GetRoom returns a room by ID or nil.
func (m *RoomManager) GetRoom(id uint32) *Room {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.rooms[id]
}

// RemoveRoom deletes a room by ID.
func (m *RoomManager) RemoveRoom(id uint32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.rooms, id)
}

// ListRooms returns all rooms matching the given type (0 = all).
func (m *RoomManager) ListRooms(roomType uint8) []*Room {
	m.mu.RLock()
	defer m.mu.RUnlock()

	var result []*Room
	for _, r := range m.rooms {
		if roomType == 0 || r.Type == roomType {
			result = append(result, r)
		}
	}
	return result
}

// UpdateMap changes the map ID for a room.
func (m *RoomManager) UpdateMap(roomID uint32, mapID uint32) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if !ok {
		return false
	}
	r.MapID = mapID
	return true
}

// AddMember adds a char to a room with their pre-encoded brief and assigned camp.
func (m *RoomManager) AddMember(roomID uint32, charID uint32, brief []byte, camp uint8) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if !ok {
		return false
	}
	// Don't add duplicates
	for _, mid := range r.Members {
		if mid == charID {
			return true
		}
	}
	r.Members = append(r.Members, charID)
	if r.MemberBriefs == nil {
		r.MemberBriefs = make(map[uint32][]byte)
	}
	if r.MemberCamps == nil {
		r.MemberCamps = make(map[uint32]uint8)
	}
	if r.MemberReady == nil {
		r.MemberReady = make(map[uint32]bool)
	}
	r.MemberBriefs[charID] = brief
	r.MemberCamps[charID] = camp
	r.MemberReady[charID] = false
	return true
}

// SetMemberBrief updates the pre-encoded brief for a member (e.g. after switching camp).
func (m *RoomManager) SetMemberBrief(roomID uint32, charID uint32, brief []byte) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if ok && r.MemberBriefs != nil {
		r.MemberBriefs[charID] = brief
	}
}

// SwitchCamp toggles a member's camp between 1 and 2.
func (m *RoomManager) SwitchCamp(roomID uint32, charID uint32) uint8 {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if !ok {
		return 1
	}
	if r.MemberCamps == nil {
		r.MemberCamps = make(map[uint32]uint8)
	}
	current := r.MemberCamps[charID]
	if current == 0 {
		current = 1
	}
	newCamp := 3 - current
	r.MemberCamps[charID] = newCamp
	if brief, has := r.MemberBriefs[charID]; has && len(brief) >= 3 {
		brief[len(brief)-3] = newCamp
	}
	return newCamp
}

// SetMemberReady updates ready state for a member and modifies brief[0].
func (m *RoomManager) SetMemberReady(roomID uint32, charID uint32, ready bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if ok {
		if r.MemberReady == nil {
			r.MemberReady = make(map[uint32]bool)
		}
		r.MemberReady[charID] = ready
		if brief, has := r.MemberBriefs[charID]; has && len(brief) > 0 {
			if ready {
				brief[0] = 1
			} else {
				brief[0] = 0
			}
		}
	}
}

// SetMemberPos sets the battle position of a member.
func (m *RoomManager) SetMemberPos(roomID uint32, charID uint32, x, y int16) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if ok {
		if r.MemberPositions == nil {
			r.MemberPositions = make(map[uint32]*MemberPos)
		}
		r.MemberPositions[charID] = &MemberPos{X: x, Y: y}
	}
}

// GetMemberPos returns the battle position of a member.
func (m *RoomManager) GetMemberPos(roomID uint32, charID uint32) (int16, int16) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	r, ok := m.rooms[roomID]
	if ok && r.MemberPositions != nil {
		if pos, has := r.MemberPositions[charID]; has {
			return pos.X, pos.Y
		}
	}
	return 250, 350
}

// NextBulletID returns the next unique bullet ID for this room.
func (m *RoomManager) NextBulletID(roomID uint32) uint32 {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if ok {
		r.NextBullet++
		return r.NextBullet
	}
	return 1
}

// MarkLoaded records that a player reached 100% loaded.
func (m *RoomManager) MarkLoaded(roomID uint32, charID uint32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if ok {
		if r.LoadedMembers == nil {
			r.LoadedMembers = make(map[uint32]bool)
		}
		r.LoadedMembers[charID] = true
	}
}

// AllLoaded returns true if every member in the room has reported 100% loaded.
func (m *RoomManager) AllLoaded(roomID uint32) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	r, ok := m.rooms[roomID]
	if !ok || len(r.Members) == 0 {
		return false
	}
	for _, mid := range r.Members {
		if !r.LoadedMembers[mid] {
			return false
		}
	}
	return true
}

// ResetLoaded clears the loaded map for a new match.
func (m *RoomManager) ResetLoaded(roomID uint32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if ok {
		r.LoadedMembers = make(map[uint32]bool)
		r.BattleStarted = false
	}
}

// SetBattleStarted atomically checks and marks the battle as started. Returns true if this call changed it from false to true.
func (m *RoomManager) SetBattleStarted(roomID uint32) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if !ok || r.BattleStarted {
		return false
	}
	r.BattleStarted = true
	return true
}

// GetMemberCamp returns the camp for a member (1 or 2).
func (m *RoomManager) GetMemberCamp(roomID uint32, charID uint32) uint8 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	r, ok := m.rooms[roomID]
	if !ok || r.MemberCamps == nil {
		return 1
	}
	camp, ok := r.MemberCamps[charID]
	if !ok || camp == 0 {
		return 1
	}
	return camp
}

// GetMembers returns a copy of room members.
func (m *RoomManager) GetMembers(roomID uint32) []uint32 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	r, ok := m.rooms[roomID]
	if !ok {
		return nil
	}
	members := make([]uint32, len(r.Members))
	copy(members, r.Members)
	return members
}

// GetMemberBriefs returns pre-encoded briefs for all members in order.
func (m *RoomManager) GetMemberBriefs(roomID uint32) [][]byte {
	m.mu.RLock()
	defer m.mu.RUnlock()
	r, ok := m.rooms[roomID]
	if !ok {
		return nil
	}
	briefs := make([][]byte, 0, len(r.Members))
	for _, mid := range r.Members {
		if b, ok := r.MemberBriefs[mid]; ok {
			briefs = append(briefs, b)
		}
	}
	return briefs
}

// SetMemberSkills records the skill templates for a member.
func (m *RoomManager) SetMemberSkills(roomID uint32, charID uint32, skills [4]uint32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.rooms[roomID]
	if !ok {
		return
	}
	if r.MemberSkills == nil {
		r.MemberSkills = make(map[uint32][4]uint32)
	}
	r.MemberSkills[charID] = skills
}

// GetMemberSkills returns the skill templates for a member.
func (m *RoomManager) GetMemberSkills(roomID uint32, charID uint32) [4]uint32 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	r, ok := m.rooms[roomID]
	if !ok || r.MemberSkills == nil {
		return [4]uint32{1001, 1002, 1003, 1004}
	}
	sk, ok := r.MemberSkills[charID]
	if !ok {
		return [4]uint32{1001, 1002, 1003, 1004}
	}
	return sk
}

// FindRoomByMember finds the room that contains charID.
func (m *Ro