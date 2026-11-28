package protocol

// ============================================================================
// PvE & Military Rank Protocol Encoders
// ============================================================================

// CityInfoWire is the wire-level PvE city (18 bytes).
type CityInfoWire struct {
	CityID    uint32
	Value     uint32
	EvalEasy  uint8
	EvalDiff  uint8
	DiffPass  uint32
	ResetTime uint32
}

// EncodeNotifyCityInfoInitFull encodes S→C 1303 with full city array.
func EncodeNotifyCityInfoInitFull(cities []CityInfoWire) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(cities)))
	for _, c := range cities {
		w.PutU32(c.CityID)
		w.PutU32(c.Value)
		w.PutU8(c.EvalEasy)
		w.PutU8(c.EvalDiff)
		w.PutU32(c.DiffPass)
		w.PutU32(c.ResetTime)
	}
	return BuildFrame(1303, 0, w.Bytes())
}

// EncodeUpdateCityInfo encodes S→C 1304 with updated city array.
func EncodeUpdateCityInfo(cities []CityInfoWire) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(cities)))
	for _, c := range cities {
		w.PutU32(c.CityID)
		w.PutU32(c.Value)
		w.PutU8(c.EvalEasy)
		w.PutU8(c.EvalDiff)
		w.PutU32(c.DiffPass)
		w.PutU32(c.ResetTime)
	}
	return BuildFrame(1304, 0, w.Bytes())
}

// EncodeNotifyUpdateCharMilitaryStar encodes S→C 85 for military star.
// Wire: u8 type=27, u32 value, u16 strLen=0
func EncodeNotifyUpdateCharMilitaryStar(stars uint32) []byte {
	w := NewWriter()
	w.PutU8(27)
	w.PutU32(stars)
	w.PutU16(0) // empty utf8
	return BuildFrame(85, 0, w.Bytes())
}

// EncodeNotifyPveRecord encodes S→C 1516.
// Simplified: map_id, passTime=0, useTime=0, 0 chars, nByte=1 (NORMAL_NOTIFY)
func EncodeNotifyPveRecord(mapID uint32) []byte {
	w := NewWriter()
	w.PutU32(mapID)
	w.PutU32(0) // passTime
	w.PutU32(0) // useTime
	w.PutU16(0) // 0 chars
	w.PutU8(1)  // NORMAL_NOTIFY
	return BuildFrame(1516, 0, w.Bytes())
}

// EncodeNotifyThew encodes S→C 1027 (stamina).
// Wire: i32 thew, i32 thewBuy, i32 thewVip
func EncodeNotifyThew(thew, thewBuy, thewVip int32) []byte {
	w := NewWriter()
	w.PutI32(thew)
	w.PutI32(thewBuy)
	w.PutI32(thewVip)
	return BuildFrame(1027, 0, w.Bytes())
}
