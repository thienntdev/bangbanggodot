package protocol

// ============================================================================
// Mail Protocol Encoders — based on Godot client protocol_schema.gd
// Wire structs:
//   MAIL_BRIEF_INFO: utf8 uuid, utf8 senderUuid, utf8 sender, utf8 title,
//                    u32 arriveTime, u32 mailType, u32 mailState,
//                    u32 sendMode, u32 affixSign, u32 createTime
//   MAIL_INSIDE_INFO: utf8 uuid, utf8 text, i32 cashNum,
//                     u16 itemCount + items, TankInstance
// ============================================================================

// MailBriefInfo is the wire-level mail brief.
type MailBriefInfo struct {
	UUID       string
	SenderUUID string
	Sender     string
	Title      string
	ArriveTime uint32
	MailType   uint32
	MailState  uint32
	SendMode   uint32
	AffixSign  uint32
	CreateTime uint32
}

func writeMailBrief(w *Writer, m *MailBriefInfo) {
	w.PutUTF8(m.UUID)
	w.PutUTF8(m.SenderUUID)
	w.PutUTF8(m.Sender)
	w.PutUTF8(m.Title)
	w.PutU32(m.ArriveTime)
	w.PutU32(m.MailType)
	w.PutU32(m.MailState)
	w.PutU32(m.SendMode)
	w.PutU32(m.AffixSign)
	w.PutU32(m.CreateTime)
}

// EncodeNotifyNoReadMailCount encodes S→C 1230.
func EncodeNotifyNoReadMailCount(count int32) []byte {
	w := NewWriter()
	w.PutI32(count)
	return BuildFrame(1230, 0, w.Bytes())
}

// EncodeNotifyMailList encodes S→C 1231.
func EncodeNotifyMailList(mails []MailBriefInfo) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(mails)))
	for i := range mails {
		writeMailBrief(w, &mails[i])
	}
	return BuildFrame(1231, 0, w.Bytes())
}

// EncodeNotifyMailInsideInfo encodes S→C 1232.
// Simplified: no items or tank instance (empty arrays).
func EncodeNotifyMailInsideInfo(uuid, text string, cashNum int32) []byte {
	w := NewWriter()
	w.PutUTF8(uuid)
	w.PutUTF8(text)
	w.PutI32(cashNum)
	w.PutU16(0) // 0 items
	// Empty TankInstance (minimum fields): write empty utf8 + all zero fields
	w.PutUTF8("")     // m_tankUuid
	w.PutU32(0)       // m_tpltId
	w.PutU8(0)        // m_level
	w.PutU32(0)       // m_nExp
	w.PutU32(0)       // m_extFlag
	w.PutU8(0)        // m_stthLevel
	w.PutU32(0)       // m_externalId
	w.PutU32(0)       // m_warCount
	w.PutU32(0)       // m_weekWarCount
	w.PutU8(0)        // m_contType
	w.PutU8(0)        // m_cashHireCount
	w.PutU8(0)        // m_coinHireCount
	w.PutU32(0)       // m_existTime
	w.PutU32(0)       // m_haloId
	w.PutU8(0)        // m_skinFrameType
	w.PutU32(0)       // m_ownTime
	w.PutU8(0)        // m_stthCount
	w.PutU32(0)       // m_comSkillId
	w.PutU8(0)        // m_crystalSchemeId
	w.PutUTF8("")     // m_talPageUuid
	w.PutU32(0)       // m_proficiencyVal
	w.PutI32(0)       // m_battleGains
	return BuildFrame(1232, 0, w.Bytes())
}

// EncodeNotifyMailOperateResult encodes S→C 1233.
// result: nonzero=success, 0=fail
func EncodeNotifyMailOperateResult(result int32, opType int32, mailUUID string) []byte {
	w := NewWriter()
	w.PutI32(result)
	w.PutI32(opType)
	w.PutUTF8(mailUUID)
	return BuildFrame(1233, 0, w.Bytes())
}

// EncodeUpdateMailBriefInfo encodes S→C 1234.
func EncodeUpdateMailBriefInfo(mail *MailBriefInfo) []byte {
	w := NewWriter()
	writeMailBrief(w, mail)
	return BuildFrame(1234, 0, w.Bytes())
}

// DecodeRequestMailOperate decodes C→S 271 body.
func DecodeRequestMailOperate(body []byte) (string, int32, error) {
	r := NewReader(body)
	uuid, err := r.GetUTF8()
	if err != nil {
		return "", 0, err
	}
	opType, err := r.GetI32()
	if err != nil {
		return "", 0, err
	}
	return uuid, opType, nil
}

// DecodeSendMail decodes C→S 270 body (raw format).
func DecodeSendMail(body []byte) (receiver, title, text string, err error) {
	r := NewReader(body)
	receiver, err = r.GetUTF8()
	if err != nil {
		return
	}
	title, err = r.GetUTF8()
	if err != nil {
		return
	}
	text, err = r.GetUTF8()
	if err != nil {
		return
	}
	return
}

// DecodeClaimMailItem decodes C→S 272 body.
func DecodeClaimMailItem(body []byte) (mailUUID, itemUUID string, err error) {
	r := NewReader(body)
	mailUUID, err = r.GetUTF8()
	if err != nil {
		return
	}
	itemUUID, err = r.GetUTF8()
	if err != nil {
		return
	}
	return
}
