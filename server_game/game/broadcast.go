package game

import "sync"

// Broadcaster allows sending messages to connected players by charID.
type Broadcaster struct {
	mu    sync.RWMutex
	conns map[uint32]Sender // charID → connection that can Send
}

// Sender is any connection that can send a binary frame and close.
type Sender interface {
	Send(frame []byte) error
	Close()
}

// NewBroadcaster creates a new broadcaster.
func NewBroadcaster() *Broadcaster {
	return &Broadcaster{
		conns: make(map[uint32]Sender),
	}
}

// Register adds a connection for a charID, returning any existing sender.
func (b *Broadcaster) Register(charID uint32, s Sender) Sender {
	b.mu.Lock()
	defer b.mu.Unlock()
	old := b.conns[charID]
	b.conns[charID] = s
	return old
}

// Unregister removes a connection for a charID only if it matches s.
func (b *Broadcaster) Unregister(charID uint32, s Sender) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.conns[charID] == s {
		delete(b.conns, charID)
	}
}

// Has checks if a charID has an active registered connection.
func (b *Broadcaster) Has(charID uint32) bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	_, ok := b.conns[charID]
	return ok
}

// SendTo sends a frame to a specific charID. Returns false if not found.
func (b *Broadcaster) SendTo(charID uint32, frame []byte) bool {
	b.mu.RLock()
	s, ok := b.conns[charID]
	b.mu.RUnlock()
	if !ok {
		return false
	}
	s.Send(frame)
	return true
}

// SendToAll sends a frame to multiple charIDs (skipping `except`).
func (b *Broadcaster) SendToAll(charIDs []uint32, except uint32, frame []byte) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	for _, id := range charIDs {
		if id == except {
			continue
		}
		if s, ok := b.conns[id]; ok {
			s.Send(frame)
		}
	}
}
