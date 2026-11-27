package game

import "sync"

// OnlinePlayer represents a player currently connected.
type OnlinePlayer struct {
	CharID   uint32
	CharUUID string
	Name     string
	Level    uint8
	AvatarID uint32
}

// OnlineTracker keeps track of all online players.
type OnlineTracker struct {
	mu      sync.RWMutex
	players map[uint32]*OnlinePlayer // keyed by charID
}

// NewOnlineTracker creates a new tracker.
func NewOnlineTracker() *OnlineTracker {
	return &OnlineTracker{
		players: make(map[uint32]*OnlinePlayer),
	}
}

// Add registers a player as online.
func (t *OnlineTracker) Add(p *OnlinePlayer) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.players[p.CharID] = p
}

// Remove takes a player offline by charID.
func (t *OnlineTracker) Remove(charID uint32) {
	t.mu.Lock()
	defer t.mu.Unlock()
	delete(t.players, charID)
}

// List returns all online players.
func (t *OnlineTracker) List() []*OnlinePlayer {
	t.mu.RLock()
	defer t.mu.RUnlock()
	result := make([]*OnlinePlayer, 0, len(t.players))
	for _, p := range t.players {
		result = append(result, p)
	}
	return result
}

// Count returns how many players are online.
func (t *OnlineTracker) Count() int {
	t.mu.RLock()
	defer t.mu.RUnlock()
	return len(t.players)
}
