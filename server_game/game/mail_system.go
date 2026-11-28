package game

import (
	"sync"
	"time"

	"github.com/google/uuid"
)

// ============================================================================
// Mail System — built from scratch based on Godot client protocol.
// Client expects:
//   C→S 270: send mail (utf8 receiver, utf8 title, utf8 body, zeros)
//   C→S 271: mail operate (utf8 uuid, i32 opType)
//   C→S 272: claim mail item (utf8 mailUuid, utf8 itemUuid)
//   S→C 1230: unread mail count (i32 count)
//   S→C 1231: mail list (u16 count, [MAIL_BRIEF_INFO])
//   S→C 1232: mail inside info (MAIL_INSIDE_INFO)
//   S→C 1233: mail operate result (i32 result, i32 opType, utf8 mailUuid)
//   S→C 1234: update mail brief info (MAIL_BRIEF_INFO)
// ============================================================================

const (
	MailOpNone       int32 = 0
	MailOpOpenBox    int32 = 1
	MailOpCloseBox   int32 = 2
	MailOpSend       int32 = 3
	MailOpRead       int32 = 4
	MailOpDelete     int32 = 5
	MailOpBack       int32 = 6
	MailOpPayCash    int32 = 7
	MailOpPickupItem int32 = 8
	MailOpPickupCash int32 = 9
	MailOpPickupTank int32 = 10

	MailStateUnread uint32 = 0
	MailStateRead   uint32 = 1
	MailStateNoPay  uint32 = 2

	MailCapacity = 30
)

// MailBrief represents one mail entry in the inbox list.
type MailBrief struct {
	UUID       string
	SenderUUID string
	Sender     string
	Title      string
	Text       string
	ArriveTime uint32
	MailType   uint32
	MailState  uint32
	SendMode   uint32 // nonzero = has gift
	AffixSign  uint32
	CreateTime uint32
}

// PlayerMailData stores all mail data for one player.
type PlayerMailData struct {
	Inbox []*MailBrief
}

// MailManager manages mail data for all players.
type MailManager struct {
	mu      sync.RWMutex
	players map[uint32]*PlayerMailData
}

func NewMailManager() *MailManager {
	return &MailManager{
		players: make(map[uint32]*PlayerMailData),
	}
}

func (m *MailManager) getOrCreate(charID uint32) *PlayerMailData {
	data, ok := m.players[charID]
	if !ok {
		data = &PlayerMailData{
			Inbox: make([]*MailBrief, 0),
		}
		m.players[charID] = data
	}
	return data
}

// GetUnreadCount returns the number of unread mails.
func (m *MailManager) GetUnreadCount(charID uint32) int32 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	data, ok := m.players[charID]
	if !ok {
		return 0
	}
	count := int32(0)
	for _, mail := range data.Inbox {
		if mail.MailState == MailStateUnread {
			count++
		}
	}
	return count
}

// GetMailList returns all mails for a player.
func (m *MailManager) GetMailList(charID uint32) []*MailBrief {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	return data.Inbox
}

// ReadMail marks a mail as read and returns the mail.
func (m *MailManager) ReadMail(charID uint32, mailUUID string) *MailBrief {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	for _, mail := range data.Inbox {
		if mail.UUID == mailUUID {
			if mail.MailState == MailStateUnread {
				mail.MailState = MailStateRead
			}
			return mail
		}
	}
	return nil
}

// DeleteMail deletes a specific mail. Returns true if found and deleted.
func (m *MailManager) DeleteMail(charID uint32, mailUUID string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	for i, mail := range data.Inbox {
		if mail.UUID == mailUUID {
			data.Inbox = append(data.Inbox[:i], data.Inbox[i+1:]...)
			return true
		}
	}
	return false
}

// DeleteReadMails deletes all read mails without gifts. Returns count deleted.
func (m *MailManager) DeleteReadMails(charID uint32) int {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)
	remaining := make([]*MailBrief, 0, len(data.Inbox))
	deleted := 0
	for _, mail := range data.Inbox {
		if mail.MailState == MailStateRead && mail.SendMode == 0 {
			deleted++
		} else {
			remaining = append(remaining, mail)
		}
	}
	data.Inbox = remaining
	return deleted
}

// SendMail sends a mail from one player to another. Returns the new mail's UUID.
func (m *MailManager) SendMail(senderID uint32, senderName string, receiverID uint32, title, body string) string {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(receiverID)

	now := uint32(time.Now().Unix())
	mail := &MailBrief{
		UUID:       "mail-" + uuid.New().String()[:32],
		SenderUUID: "",
		Sender:     senderName,
		Title:      title,
		Text:       body,
		ArriveTime: now + 7*24*3600, // 7 day expiry
		MailType:   0,
		MailState:  MailStateUnread,
		SendMode:   0,
		AffixSign:  0,
		CreateTime: now,
	}

	// Enforce capacity
	if len(data.Inbox) >= MailCapacity {
		data.Inbox = data.Inbox[:MailCapacity-1]
	}
	data.Inbox = append([]*MailBrief{mail}, data.Inbox...)
	return mail.UUID
}

// SendSystemMail sends a system mail to a player. Returns the new mail.
func (m *MailManager) SendSystemMail(charID uint32, title, body string) *MailBrief {
	m.mu.Lock()
	defer m.mu.Unlock()
	data := m.getOrCreate(charID)

	now := uint32(time.Now().Unix())
	mail := &MailBrief{
		UUID:       "mail-" + uuid.New().String()[:32],
		SenderUUID: "",
		Sender:     "Hệ thống",
		Title:      title,
		Text:       body,
		ArriveTime: now + 30*24*3600,
		MailType:   1,
		MailState:  MailStateUnread,
		SendMode:   0,
		AffixSign:  0,
		CreateTime: now,
	}

	if len(data.Inbox) >= MailCapacity {
		data.Inbox = data.Inbox[:MailCapacity-1]
	}
	data.Inbox = append([]*MailBrief{mail}, data.Inbox...)
	return mail
}
