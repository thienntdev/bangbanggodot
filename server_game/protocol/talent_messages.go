package protocol

// ============================================================================
// Talent Protocol Encoders — based on Godot client protocol_schema.gd
// Wire structs:
//   TALENT_GRID: u32 talentId, u16 level
//   TALENT_PAGE: utf8 uuid, utf8 name, array[u16]<TALENT_GRID>, u32 createTime
// ============================================================================

// TalentGrid is the wire-level talent node.
type TalentGrid struct {
	TalentID uint32
	Level    uint16
}

// TalentPage is the wire-level talent page.
type TalentPage struct {
	UUID       string
	Name       string
	Tree       []TalentGrid
	CreateTime uint32
}

// writeTalentPage writes a TALENT_PAGE struct to the writer.
func writeTalentPage(w *Writer, p *TalentPage) {
	w.PutUTF8(p.UUID)
	w.PutUTF8(p.Name)
	w.PutU16(uint16(len(p.Tree)))
	for _, g := range p.Tree {
		w.PutU32(g.TalentID)
		w.PutU16(g.Level)
	}
	w.PutU32(p.CreateTime)
}

// EncodeNotifyUpdateTalentPage encodes S→C 1450.
// opType: 1=add, 2=save
func EncodeNotifyUpdateTalentPage(opType uint32, page *TalentPage) []byte {
	w := NewWriter()
	w.PutU32(opType)
	writeTalentPage(w, page)
	return BuildFrame(1450, 0, w.Bytes())
}

// EncodeNotifyOpTalentPage encodes S→C 1451.
// opType: 3=reset, 4=delete
func EncodeNotifyOpTalentPage(opType uint32, pageUUID string) []byte {
	w := NewWriter()
	w.PutU32(opType)
	w.PutUTF8(pageUUID)
	return BuildFrame(1451, 0, w.Bytes())
}

// EncodeNotifyTalentInfo encodes S→C 1452.
// Full talent data: all pages + total points + buy count
func EncodeNotifyTalentInfo(pages []TalentPage, totalPoint uint32, buyPageCount uint8) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(pages)))
	for i := range pages {
		writeTalentPage(w, &pages[i])
	}
	w.PutU32(totalPoint)
	w.PutU8(buyPageCount)
	return BuildFrame(1452, 0, w.Bytes())
}

// EncodeNotifyTalentTotalPoint encodes S→C 1453.
func EncodeNotifyTalentTotalPoint(totalPoint uint32) []byte {
	w := NewWriter()
	w.PutU32(totalPoint)
	return BuildFrame(1453, 0, w.Bytes())
}

// DecodeTalentPage decodes a TALENT_PAGE from reader. Returns page and error.
func DecodeTalentPage(r *Reader) (*TalentPage, error) {
	uuid, err := r.GetUTF8()
	if err != nil {
		return nil, err
	}
	name, err := r.GetUTF8()
	if err != nil {
		return nil, err
	}
	count, err := r.GetU16()
	if err != nil {
		return nil, err
	}
	tree := make([]TalentGrid, count)
	for i := uint16(0); i < count; i++ {
		tid, err := r.GetU32()
		if err != nil {
			return nil, err
		}
		lvl, err := r.GetU16()
		if err != nil {
			return nil, err
		}
		tree[i] = TalentGrid{TalentID: tid, Level: lvl}
	}
	ct, err := r.GetU32()
	if err != nil {
		return nil, err
	}
	return &TalentPage{
		UUID:       uuid,
		Name:       name,
		Tree:       tree,
		CreateTime: ct,
	}, nil
}
