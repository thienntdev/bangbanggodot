package protocol

// Quest/Stage/Sign-in protocol encoders — built from client binary protocol.
// All formats match what game_client.gd decodes.

// ============================================================================
// Quest messages (S→C)
// ============================================================================

// QuestData is the 28-byte wire format for one quest entry.
type QuestData struct {
	QuestID uint32
	State   uint32
	Count   uint32
	Field3  uint32
	Field4  uint32
	Field5  uint32
	Field6  uint32
}

// EncodeNotifyQuestList builds message 1250.
// Client parses: u16 count, [count × 28B QuestData], u32 kind
// kind=1: full replace; kind=2: append (merge).
func EncodeNotifyQuestList(quests []QuestData, kind uint32) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(quests)))
	for _, q := range quests {
		w.PutU32(q.QuestID)
		w.PutU32(q.State)
		w.PutU32(q.Count)
		w.PutU32(q.Field3)
		w.PutU32(q.Field4)
		w.PutU32(q.Field5)
		w.PutU32(q.Field6)
	}
	w.PutU32(kind) // trailing kind byte (client reads s32 at offset 2+count*28)
	return BuildFrame(MsgNotifyQuestList, 0, w.Bytes())
}

// EncodeNotifyQuestUpdate builds message 1251 — single quest update (28 bytes).
func EncodeNotifyQuestUpdate(q QuestData) []byte {
	w := NewWriter()
	w.PutU32(q.QuestID)
	w.PutU32(q.State)
	w.PutU32(q.Count)
	w.PutU32(q.Field3)
	w.PutU32(q.Field4)
	w.PutU32(q.Field5)
	w.PutU32(q.Field6)
	return BuildFrame(MsgNotifyQuestUpdate, 0, w.Bytes())
}

// EncodeNotifyQuestRemove builds message 1252 — remove quest(s).
// Client parses: u16 count, [count × u32 questID]
func EncodeNotifyQuestRemove(questIDs []uint32) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(questIDs)))
	for _, id := range questIDs {
		w.PutU32(id)
	}
	return BuildFrame(MsgNotifyQuestRemove, 0, w.Bytes())
}

// EncodeNotifyQuestFailed builds message 1254.
func EncodeNotifyQuestFailed(questID uint32) []byte {
	w := NewWriter()
	w.PutU32(questID)
	return BuildFrame(MsgNotifyQuestFailed, 0, w.Bytes())
}

// ============================================================================
// Stage messages (S→C)
// ============================================================================

// EncodeNotifyStageInfo builds message 1306.
// Client parses: u32 stage, u32 reward, u32 reaped, u32 next, u32 flag, u32 level, u32 value (28B).
func EncodeNotifyStageInfo(stageID, reward, reaped, next, flag, level, value uint32) []byte {
	w := NewWriter()
	w.PutU32(stageID)
	w.PutU32(reward)
	w.PutU32(reaped)
	w.PutU32(next)
	w.PutU32(flag)
	w.PutU32(level)
	w.PutU32(value)
	return BuildFrame(MsgNotifyStageInfo, 0, w.Bytes())
}

// EncodeNotifyStageReaped builds message 1307.
// Client parses: u32 result, u32 stageID
func EncodeNotifyStageReaped(result, stageID uint32) []byte {
	w := NewWriter()
	w.PutU32(result)
	w.PutU32(stageID)
	return BuildFrame(MsgNotifyStageReaped, 0, w.Bytes())
}

// EncodeNotifyStageClear builds message 1308.
// Client parses: u32 stageID, [u32 extra]
func EncodeNotifyStageClear(stageID uint32) []byte {
	w := NewWriter()
	w.PutU32(stageID)
	w.PutU32(0) // extra
	return BuildFrame(MsgNotifyStageClear, 0, w.Bytes())
}

// EncodeNotifyStageProgress builds message 1309.
// Client parses: u32 type, u16 count, [count × u32 now], u16 topCount, [topCount × u32 top]
func EncodeNotifyStageProgress(progressType uint32, now []uint32, top []uint32) []byte {
	w := NewWriter()
	w.PutU32(progressType)
	w.PutU16(uint16(len(now)))
	for _, v := range now {
		w.PutU32(v)
	}
	w.PutU16(uint16(len(top)))
	for _, v := range top {
		w.PutU32(v)
	}
	return BuildFrame(MsgNotifyStageProgress, 0, w.Bytes())
}

// ============================================================================
// Sign-in messages (S→C)
// ============================================================================

// EncodeNotifySignInInfo builds message 1400.
// Client parses: u32 flag, u32 vip_flag, u32 year, u32 month, u32 day, u32 count, u32 stage (28B).
func EncodeNotifySignInInfo(flag, vipFlag, year, month, day, count, stage uint32) []byte {
	w := NewWriter()
	w.PutU32(flag)
	w.PutU32(vipFlag)
	w.PutU32(year)
	w.PutU32(month)
	w.PutU32(day)
	w.PutU32(count)
	w.PutU32(stage)
	return BuildFrame(MsgNotifySignInInfo, 0, w.Bytes())
}

// EncodeNotifyLimitList builds message 1045.
// Client parses: u16 count, [count × (u32 limitID, s32 value)]
func EncodeNotifyLimitList(limits map[uint32]int32) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(limits)))
	for id, val := range limits {
		w.PutU32(id)
		w.PutI32(val)
	}
	return BuildFrame(MsgNotifyLimitList, 0, w.Bytes())
}

// EncodeNotifyVipInfo builds message 1049.
// Client parses: u32 vipPoints, u32 vipTime, u32 ?, u32 vipPointsAddToday, u32 superVipTime (20B).
func EncodeNotifyVipInfo(vipPoints, vipTime, reserved, addToday, superVipTime uint32) []byte {
	w := NewWriter()
	w.PutU32(vipPoints)
	w.PutU32(vipTime)
	w.PutU32(reserved)
	w.PutU32(addToday)
	w.PutU32(superVipTime)
	return BuildFrame(MsgNotifyVipInfo, 0, w.Bytes())
}

// EncodeNotifyCashbackInfo builds message 81.
// Client parses: u32 cashback_times, u32 cashback_picked
func EncodeNotifyCashbackInfo(times, picked uint32) []byte {
	w := NewWriter()
	w.PutU32(times)
	w.PutU32(picked)
	return BuildFrame(MsgNotifyCashbackInfo, 0, w.Bytes())
}
