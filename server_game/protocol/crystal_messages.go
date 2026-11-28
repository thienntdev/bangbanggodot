package protocol

// ============================================================================
// Crystal Protocol Encoders — based on Godot client protocol_schema.gd
// Wire structs:
//   CharCrystalSchemeInfo: u32 schemeId + 30 × u32 posN_item_id (124 bytes)
//   CharCrystalSchemeName: u32 schemeId, utf8 name
// ============================================================================

const CrystalSlots = 30

// CrystalSchemeInfo is the wire-level crystal scheme (124 bytes fixed).
type CrystalSchemeInfo struct {
	SchemeID uint32
	Slots    [CrystalSlots]uint32
}

// EncodeNotifyCrystalSchemeInfo encodes S→C 1454.
func EncodeNotifyCrystalSchemeInfo(schemes []CrystalSchemeInfo) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(schemes)))
	for _, s := range schemes {
		w.PutU32(s.SchemeID)
		for i := 0; i < CrystalSlots; i++ {
			w.PutU32(s.Slots[i])
		}
	}
	return BuildFrame(1454, 0, w.Bytes())
}

// EncodeNotifyCrystalSchemeNames encodes S→C 1455.
func EncodeNotifyCrystalSchemeNames(names map[uint32]string) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(names)))
	for id, name := range names {
		w.PutU32(id)
		w.PutUTF8(name)
	}
	return BuildFrame(1455, 0, w.Bytes())
}

// EncodeNotifyRenameCrystalResult encodes S→C 1457.
// result: 0=success, 1=fail
func EncodeNotifyRenameCrystalResult(result uint32) []byte {
	w := NewWriter()
	w.PutU32(result)
	return BuildFrame(1457, 0, w.Bytes())
}

// EncodeNotifyUpgradeCrystalResult encodes S→C 1459.
// result: 0=success
func EncodeNotifyUpgradeCrystalResult(result uint32) []byte {
	w := NewWriter()
	w.PutU32(result)
	return BuildFrame(1459, 0, w.Bytes())
}

// EncodeNotifyCrystalMakeFreeCoolTime encodes S→C 1461.
func EncodeNotifyCrystalMakeFreeCoolTime(coolEndTime uint32) []byte {
	w := NewWriter()
	w.PutU32(coolEndTime)
	return BuildFrame(1461, 0, w.Bytes())
}

// DecodeSaveCrystalScheme decodes C→S 424 body (124 bytes).
func DecodeSaveCrystalScheme(body []byte) (*CrystalSchemeInfo, error) {
	r := NewReader(body)
	schemeID, err := r.GetU32()
	if err != nil {
		return nil, err
	}
	var slots [CrystalSlots]uint32
	for i := 0; i < CrystalSlots; i++ {
		slots[i], err = r.GetU32()
		if err != nil {
			return nil, err
		}
	}
	return &CrystalSchemeInfo{SchemeID: schemeID, Slots: slots}, nil
}

// DecodeRenameCrystalScheme decodes C→S 425 body.
func DecodeRenameCrystalScheme(body []byte) (uint32, string, error) {
	r := NewReader(body)
	schemeID, err := r.GetU32()
	if err != nil {
		return 0, "", err
	}
	name, err := r.GetUTF8()
	if err != nil {
		return 0, "", err
	}
	return schemeID, name, nil
}

// DecodeCrystalForge decodes C→S 426 body.
func DecodeCrystalForge(body []byte) (bool, []uint32, error) {
	r := NewReader(body)
	sellFlag, err := r.GetU32()
	if err != nil {
		return false, nil, err
	}
	count, err := r.GetU16()
	if err != nil {
		return false, nil, err
	}
	items := make([]uint32, count)
	for i := uint16(0); i < count; i++ {
		items[i], err = r.GetU32()
		if err != nil {
			return false, nil, err
		}
	}
	return sellFlag == 1, items, nil
}

// DecodeSetCurCrystalScheme decodes C→S 427 body.
func DecodeSetCurCrystalScheme(body []byte) (uint32, string, error) {
	r := NewReader(body)
	schemeID, err := r.GetU32()
	if err != nil {
		return 0, "", err
	}
	tankUUID, err := r.GetUTF8()
	if err != nil {
		return 0, "", err
	}
	return schemeID, tankUUID, nil
}

// DecodeCrystalMake decodes C→S 430 body.
func DecodeCrystalMake(body []byte) (uint32, error) {
	r := NewReader(body)
	kind, err := r.GetU32()
	if err != nil {
		return 0, err
	}
	return kind, nil
}
