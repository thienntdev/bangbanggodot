package protocol

// ============================================================================
// Award & Item-use Result Protocol Encoders
// Based on client protocol_schema.gd:
//
// NotifySettleAward (1104):
//   u32 m_opType
//   SettleAwardInfo m_info:
//     i32 m_cash, i32 m_gift, i32 m_golden, i32 m_glory
//     array[u16]<SettleItemVec>:
//       u32 m_nType
//       array[u16]<SettleItemInfo>:
//         u32 m_itemId, i32 m_count
//     array[u16]<u32> m_tankVec
//     i32 m_exp
//     u16 m_fizz
//   u8 m_isShow
//   u32 m_nExtInfo
//
// NotifyClientUseItemFailedMessage (1113):
//   u32 m_contType, i16 m_slotNo
// ============================================================================

// AwardItem represents one item in a settle award group.
type AwardItem struct {
	ItemID uint32
	Count  int32
}

// AwardGroup represents one group of items in settle award.
type AwardGroup struct {
	GroupType uint32      // 0=base, 7=base_extra, 8=exchange, 19=crystal
	Items     []AwardItem
}

// SettleAwardInfo contains the full award information.
type SettleAwardInfo struct {
	Cash     int32
	Gift     int32  // gift currency (xu khóa)
	Golden   int32  // golden currency
	Glory    int32
	Groups   []AwardGroup
	TankVec  []uint32  // tank template IDs granted
	Exp      int32
	Fizz     uint16
}

// EncodeNotifySettleAward encodes S→C 1104 (NotifySettleAward).
// opType: identifies the kind of award (0=item use, 1=PvE, 8=exchange, 19=crystal, etc.)
// isShow: 1=show popup, 0=silent
// extInfo: extra info (usually 0)
func EncodeNotifySettleAward(opType uint32, info *SettleAwardInfo, isShow uint8, extInfo uint32) []byte {
	w := NewWriter()
	// m_opType
	w.PutU32(opType)

	// SettleAwardInfo
	w.PutI32(info.Cash)
	w.PutI32(info.Gift)
	w.PutI32(info.Golden)
	w.PutI32(info.Glory)

	// m_settleItemVec: array of SettleItemVec
	w.PutU16(uint16(len(info.Groups)))
	for _, g := range info.Groups {
		w.PutU32(g.GroupType)
		w.PutU16(uint16(len(g.Items)))
		for _, item := range g.Items {
			w.PutU32(item.ItemID)
			w.PutI32(item.Count)
		}
	}

	// m_tankVec: array of u32
	w.PutU16(uint16(len(info.TankVec)))
	for _, t := range info.TankVec {
		w.PutU32(t)
	}

	// m_exp, m_fizz
	w.PutI32(info.Exp)
	w.PutU16(info.Fizz)

	// m_isShow
	w.PutU8(isShow)

	// m_nExtInfo
	w.PutU32(extInfo)

	return BuildFrame(MsgNotifySettleAward, 0, w.Bytes())
}

// EncodeNotifyItemFailed encodes S→C 1113 (NotifyClientUseItemFailedMessage).
func EncodeNotifyItemFailed(contType uint32, slotNo int16) []byte {
	w := NewWriter()
	w.PutU32(contType)
	w.PutI16(slotNo)
	return BuildFrame(MsgNotifyItemFailed, 0, w.Bytes())
}

// EncodeNotifyItemRemove encodes S→C 1103 (NotifyDeleteItem).
// Removes items by slot number and UUID from a container.
func EncodeNotifyItemRemove(contType uint32, slots []int16, uuids []string) []byte {
	w := NewWriter()
	w.PutU32(contType)
	// m_slotVec
	w.PutU16(uint16(len(slots)))
	for _, s := range slots {
		w.PutI16(s)
	}
	// m_itemUuidVec
	w.PutU16(uint16(len(uuids)))
	for _, u := range uuids {
		w.PutUTF8(u)
	}
	return BuildFrame(MsgNotifyItemRemove, 0, w.Bytes())
}

// EncodeNotifyItemAddFromPlayerItem encodes S→C 1102 for a granted item.
// Convenience wrapper that converts game-layer PlayerItem fields into
// the protocol ItemInstance and calls EncodeUpdateItemInstance.
type PlayerItemData struct {
	ItemUuid   string
	ContType   uint8
	SlotNo     int16
	TemplateID uint32
	Count      int32
	Level      uint8
	UpLevel    uint8
	Exp        int32
	Rank       uint8
	UpCost     int32
	RankCost   int32
	LifeTime   uint32
	ExtFlag    uint32
	CreateTime uint32
}

// EncodeNotifyItemAdd builds a 1102 message from raw item data.
func EncodeNotifyItemAdd(item PlayerItemData) []byte {
	it := &ItemInstance{
		ItemUuid:   item.ItemUuid,
		TemplateID: item.TemplateID,
		LifeTime:   item.LifeTime,
		ExtFlag:    item.ExtFlag,
		Count:      item.Count,
		Level:      item.Level,
		UpLevel:    item.UpLevel,
		Exp:        item.Exp,
		Rank:       item.Rank,
		UpCost:     item.UpCost,
		RankCost:   item.RankCost,
		CreateTime: item.CreateTime,
		SlotNo:     item.SlotNo,
	}
	return EncodeUpdateItemInstance(uint32(item.ContType), it)
}
