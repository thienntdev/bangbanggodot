package protocol

import "fmt"

// Decoders for client→server messages needed in the login flow.

// DecodeRequestProtocolVersion reads message 52.
// Fields: m_auth_ver(u32), m_gate_ver(u32), m_mixAuth(u32), m_client_ver(utf8)
type RequestProtocolVersion struct {
	AuthVer   uint32
	GateVer   uint32
	MixAuth   uint32
	ClientVer string
}

func DecodeRequestProtocolVersion(body []byte) (*RequestProtocolVersion, error) {
	r := NewReader(body)
	msg := &RequestProtocolVersion{}
	var err error
	if msg.AuthVer, err = r.GetU32(); err != nil {
		return nil, err
	}
	if msg.GateVer, err = r.GetU32(); err != nil {
		return nil, err
	}
	if msg.MixAuth, err = r.GetU32(); err != nil {
		return nil, err
	}
	if msg.ClientVer, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	return msg, nil
}

// DecodeRequestAuthLogin reads message 51.
// Fields: m_microclient(u8), m_name(utf8), m_passwd(utf8), m_adult(utf8),
//         m_time(utf8), m_platform(utf8), m_channel(utf8), m_token(utf8),
//         m_passport(utf8), m_clientSid(u32)
type RequestAuthLogin struct {
	MicroClient uint8
	Name        string
	Passwd      string
	Adult       string
	Time        string
	Platform    string
	Channel     string
	Token       string
	Passport    string
	ClientSid   uint32
}

func DecodeRequestAuthLogin(body []byte) (*RequestAuthLogin, error) {
	r := NewReader(body)
	msg := &RequestAuthLogin{}
	var err error
	if msg.MicroClient, err = r.GetU8(); err != nil {
		return nil, err
	}
	if msg.Name, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.Passwd, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.Adult, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.Time, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.Platform, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.Channel, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.Token, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.Passport, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.ClientSid, err = r.GetU32(); err != nil {
		return nil, err
	}
	return msg, nil
}

// DecodeRequestServerLogin reads message 54.
// Fields: m_session(u32), m_nAcctId(u32)
type RequestServerLogin struct {
	Session uint32
	AcctID  uint32
}

func DecodeRequestServerLogin(body []byte) (*RequestServerLogin, error) {
	r := NewReader(body)
	msg := &RequestServerLogin{}
	var err error
	if msg.Session, err = r.GetU32(); err != nil {
		return nil, err
	}
	if msg.AcctID, err = r.GetU32(); err != nil {
		return nil, err
	}
	return msg, nil
}

// DecodeWorldEnterMessage reads message 56.
// Fields: m_char_uuid(utf8), m_loginId(utf8), m_accountId(u32), m_strEnterKey(utf8), m_bIsFirstLogin(i16)
type WorldEnterMsg struct {
	CharUuid     string
	LoginID      string
	AccountID    uint32
	EnterKey     string
	IsFirstLogin int16
}

func DecodeWorldEnterMessage(body []byte) (*WorldEnterMsg, error) {
	r := NewReader(body)
	msg := &WorldEnterMsg{}
	var err error
	if msg.CharUuid, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.LoginID, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.AccountID, err = r.GetU32(); err != nil {
		return nil, err
	}
	if msg.EnterKey, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.IsFirstLogin, err = r.GetI16(); err != nil {
		return nil, err
	}
	return msg, nil
}

// DecodeRequestContainerItem reads message 165.
type RequestContainerItem struct {
	ContType uint32
}

func DecodeRequestContainerItem(body []byte) (*RequestContainerItem, error) {
	r := NewReader(body)
	c, err := r.GetU32()
	if err != nil {
		return nil, err
	}
	return &RequestContainerItem{ContType: c}, nil
}

// DecodeRequestUseItem reads message 153.
type RequestUseItem struct {
	ContType   uint32
	SlotNo     int16
	TargetUuid string
	Count      int32
	Auto       uint8
}

func DecodeRequestUseItem(body []byte) (*RequestUseItem, error) {
	r := NewReader(body)
	msg := &RequestUseItem{}
	var err error
	if msg.ContType, err = r.GetU32(); err != nil {
		return nil, err
	}
	if msg.SlotNo, err = r.GetI16(); err != nil {
		return nil, err
	}
	if msg.TargetUuid, err = r.GetUTF8(); err != nil {
		return nil, err
	}
	if msg.Count, err = r.GetI32(); err != nil {
		return nil, err
	}
	if msg.Auto, err = r.GetU8(); err != nil {
		return nil, err
	}
	return msg, nil
}

// DecodeRequestCleanUpCont reads message 152.
type RequestCleanUpCont struct {
	ContType uint32
}

func DecodeRequestCleanUpCont(body []byte) (*RequestCleanUpCont, error) {
	r := NewReader(body)
	c, err := r.GetU32()
	if err != nil {
		return nil, err
	}
	return &RequestCleanUpCont{ContType: c}, nil
}

// DecodeTankUUIDOnly reads raw message 200, 203 or 204.
func DecodeTankUUIDOnly(body []byte) (string, error) {
	r := NewReader(body)
	return r.GetUTF8()
}

// RequestBuyGoods reads message 250 (TradeMessage.BuyGoodsMessage).
// Fields: m_type(i32), m_info(GoodsBuyInfo: goodsId(u32), coinType(u32), price(i32), count(i32)), m_coinVec(...)
type RequestBuyGoods struct {
	BuyType  int32
	GoodsID  uint32
	CoinType uint32
	Price    int32
	Count    int32
}

func DecodeBuyGoodsMessage(body []byte) (*RequestBuyGoods, error) {
	r := NewReader(body)
	msg := &RequestBuyGoods{}
	var err error
	if msg.BuyType, err = r.GetI32(); err != nil {
		return nil, err
	}
	if msg.GoodsID, err = r.GetU32(); err != nil {
		return nil, err
	}
	if msg.CoinType, err = r.GetU32(); err != nil {
		return nil, err
	}
	if msg.Price, err = r.GetI32(); err != nil {
		return nil, err
	}
	if msg.Count, err = r.GetI32(); err != nil {
		return nil, err
	}
	return msg, nil
}

// RequestCreateRoom reads message 600 (RoomMessage.RequestCreateRoom).
type RequestCreateRoom struct {
	BType    uint8
	BMode    uint8
	MapID    uint32
	Password uint32
	Name     string
	ItemID   uint32
}

func DecodeRequestCreateRoom(body []byte) (*RequestCreateRoom, error) {
	if len(body) < 10 {
		return &RequestCreateRoom{BType: 1, BMode: 1, MapID: 101, Name: "Phòng 5v5"}, nil
	}
	r := NewReader(body)
	bType, _ := r.GetU8()
	bMode, _ := r.GetU8()
	mapID, _ := r.GetU32()
	password, _ := r.GetU32()
	name, _ := r.GetUTF8()
	var itemID uint32
	if r.Remaining() >= 4 {
		itemID, _ = r.GetU32()
	}
	if name == "" {
		name = "Phòng 5v5"
	}
	if mapID == 0 {
		mapID = 101
	}
	return &RequestCreateRoom{
		BType:    bType,
		BMode:    bMode,
		MapID:    mapID,
		Password: password,
		Name:     name,
		ItemID:   itemID,
	}, nil
}

// RequestMoveForward reads message 501.
// Fields: m_start_x(u16), m_start_y(u16), m_direction(u8), m_sceneId(u32)
type RequestMoveForward struct {
	StartX    uint16
	StartY    uint16
	Direction uint8
	SceneID   uint32
}

func DecodeRequestMoveForward(body []byte) (*RequestMoveForward, error) {
	if len(body) < 9 {
		return nil, fmt.Errorf("body too short for RequestMoveForward: %d", len(body))
	}
	r := NewReader(body)
	sx, _ := r.GetU16()
	sy, _ := r.GetU16()
	dir, _ := r.GetU8()
	sc, _ := r.GetU32()
	return &RequestMoveForward{
		StartX:    sx,
		StartY:    sy,
		Direction: dir,
		SceneID:   sc,
	}, nil
}

// RequestUseSkill reads message 503.
// Fields: m_sceneId(u32), m_targetId(u32), m_soltNo(u8), m_destX(i16), m_destY(i16)
type RequestUseSkill struct {
	SceneID  uint32
	TargetID uint32
	SlotNo   uint8
	DestX    int16
	DestY    int16
}

func DecodeRequestUseSkill(body []byte) (*RequestUseSkill, error) {
	if len(body) < 13 {
		return nil, fmt.Errorf("body too short for RequestUseSkill: %d", len(body))
	}
	r := NewReader(body)
	sc, _ := r.GetU32()
	tg, _ := r.GetU32()
	slot, _ := r.GetU8()
	dx, _ := r.GetI16()
	dy, _ := r.GetI16()
	return &RequestUseSkill{
		SceneID:  sc,
		TargetID: tg,
		SlotNo:   slot,
		DestX:    dx,
		DestY:    dy,
	}, nil
}

