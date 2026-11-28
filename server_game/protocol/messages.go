package protocol

// Messages contains encoders for all server→client messages needed
// for the login flow, following the schemas in protocol_schema.gd.

// EncodeVersionOk builds the raw 903 response.
// The client checks: frame.size() == 20 (8 header + 12 body)
// Body is 3 × u32: auth_ver, gate_ver, mixAuth echoed back.
func EncodeVersionOk(authVer, gateVer, mixAuth uint32) []byte {
	w := NewWriter()
	w.PutU32(authVer)
	w.PutU32(gateVer)
	w.PutU32(mixAuth)
	return BuildFrame(MsgVersionOk, 0, w.Bytes())
}

// EncodeLoginOk builds message 901 (AuthMessage.LoginOk).
// Fields: m_sessionkey(u32), m_expire_time(u32), m_has_char(u32), m_nAcctId(u32)
func EncodeLoginOk(sessionKey, expireTime, hasChar, acctID uint32) []byte {
	w := NewWriter()
	w.PutU32(sessionKey)
	w.PutU32(expireTime)
	w.PutU32(hasChar)
	w.PutU32(acctID)
	return BuildFrame(MsgLoginOk, 0, w.Bytes())
}

// EncodeLoginFail builds message 902 (AuthMessage.LoginFail).
// Fields: m_reason(i32), m_uOpenTime(u32), m_errMsg(utf8)
func EncodeLoginFail(reason int32, errMsg string) []byte {
	w := NewWriter()
	w.PutI32(reason)
	w.PutU32(0)
	w.PutUTF8(errMsg)
	return BuildFrame(MsgLoginFail, 0, w.Bytes())
}

// EncodeCloseSessionConfirm builds message 909 (AuthMessage.CloseSessionConfirm).
// Informs client that session was closed (e.g. logged in on another client).
func EncodeCloseSessionConfirm(reason uint32) []byte {
	w := NewWriter()
	w.PutU32(reason)
	return BuildFrame(MsgCloseSessionConfirm, 0, w.Bytes())
}

// EncodeRegionServerList builds message 906 (AuthMessage.RegionServerList).
// Contains array of REGION_INFO structs.
func EncodeRegionServerList(regions []RegionInfo) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(regions)))
	for _, r := range regions {
		w.PutU32(r.RegionID)
		w.PutUTF8(r.RegionName)
		w.PutUTF8(r.GateRealm)
		w.PutU16(r.GatePort)
		w.PutUTF8(r.CommRealm)
		w.PutU16(r.CommPort)
		w.PutI8(r.CurLoad)
		w.PutI8(r.IsPvP)
		w.PutU32(r.OpenTime)
	}
	return BuildFrame(MsgRegionServerList, 0, w.Bytes())
}

type RegionInfo struct {
	RegionID   uint32
	RegionName string
	GateRealm  string
	GatePort   uint16
	CommRealm  string
	CommPort   uint16
	CurLoad    int8
	IsPvP      int8
	OpenTime   uint32
}

// EncodeWorldEnterConfirm builds message 1005 (WorldMessage.WorldEnterConfirm).
// Fields: m_account_oid(u32), m_game_token(u32)
func EncodeWorldEnterConfirm(accountOid, gameToken uint32) []byte {
	w := NewWriter()
	w.PutU32(accountOid)
	w.PutU32(gameToken)
	return BuildFrame(MsgWorldEnterConfirm, 0, w.Bytes())
}

// EncodeNotifyCharList builds message 1014 (CharMessage.NotifyCharList).
// Array of CharPickInfo { m_basic: CHAR_BASIC, m_charUuid: utf8 }
func EncodeNotifyCharList(chars []CharPickInfo) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(chars)))
	for _, c := range chars {
		writeCharBasic(w, &c.Basic)
		w.PutUTF8(c.CharUuid)
	}
	return BuildFrame(MsgNotifyCharList, 0, w.Bytes())
}

type CharPickInfo struct {
	Basic    CharBasic
	CharUuid string
}

// CharBasic matches sixcube.protocol.BulkDataType.CHAR_BASIC (40 fields, min 130 bytes).
type CharBasic struct {
	AccountOid         uint32
	Sexes              uint8
	Level              uint8
	VipTime            uint32
	Exp                int32
	TankExpDoubleTime  uint32
	ExpDoubleTime      uint32
	TokenDoubleTime    uint32
	MaterialDoubleTime uint32
	TokenDoubleUse     uint16
	MaterialDoubleUse  uint16
	TankExpDoubleUse   uint16
	MilLevel           uint16
	MilExp             int32
	SprayID            uint32
	VipPoints          uint32
	VipPointsAddToday  uint16
	AvatarID           uint32
	DecorateID         uint32
	IFizz              int16
	IWeekFizz          int16
	VipTankTryTime     uint32
	SuperVipTime       uint32
	ActionFlag         uint32
	Thew               int16
	ThewBuy            int16
	CreateTime         uint32
	OnlineTime         uint32
	HonorID            uint32
	GoldenPool         uint32
	RlteStageCount     uint32
	SettingFlag        uint32
	CashbackTimes      uint32
	CashbackPicked     uint32
	PrenticeCashback   uint32
	GraduateCount      uint16
	GroceryAdd         uint16
	GmLevel            uint8
	HasTankSoulRank    uint8
	NMilitaryStar      uint32
	Name               string
	CharUuid           string
}

func writeCharBasic(w *Writer, b *CharBasic) {
	w.PutU32(b.AccountOid)
	w.PutU8(b.Sexes)
	w.PutU8(b.Level)
	w.PutU32(b.VipTime)
	w.PutI32(b.Exp)
	w.PutU32(b.TankExpDoubleTime)
	w.PutU32(b.ExpDoubleTime)
	w.PutU32(b.TokenDoubleTime)
	w.PutU32(b.MaterialDoubleTime)
	w.PutU16(b.TokenDoubleUse)
	w.PutU16(b.MaterialDoubleUse)
	w.PutU16(b.TankExpDoubleUse)
	w.PutU16(b.MilLevel)
	w.PutI32(b.MilExp)
	w.PutU32(b.SprayID)
	w.PutU32(b.VipPoints)
	w.PutU16(b.VipPointsAddToday)
	w.PutU32(b.AvatarID)
	w.PutU32(b.DecorateID)
	w.PutI16(b.IFizz)
	w.PutI16(b.IWeekFizz)
	w.PutU32(b.VipTankTryTime)
	w.PutU32(b.SuperVipTime)
	w.PutU32(b.ActionFlag)
	w.PutI16(b.Thew)
	w.PutI16(b.ThewBuy)
	w.PutU32(b.CreateTime)
	w.PutU32(b.OnlineTime)
	w.PutU32(b.HonorID)
	w.PutU32(b.GoldenPool)
	w.PutU32(b.RlteStageCount)
	w.PutU32(b.SettingFlag)
	w.PutU32(b.CashbackTimes)
	w.PutU32(b.CashbackPicked)
	w.PutU32(b.PrenticeCashback)
	w.PutU16(b.GraduateCount)
	w.PutU16(b.GroceryAdd)
	w.PutU8(b.GmLevel)
	w.PutU8(b.HasTankSoulRank)
	w.PutU32(b.NMilitaryStar)
	w.PutUTF8(b.Name)
	w.PutUTF8(b.CharUuid)
}

// CharCurrency matches sixcube.protocol.BulkDataType.CHAR_CURRENCY.
type CharCurrency struct {
	Cash         int32
	Golden       int32
	Silver       int32
	Honor        int32
	Crystal      int32
	PresentPoint int32
}

func writeCharCurrency(w *Writer, c *CharCurrency) {
	w.PutI32(c.Cash)
	w.PutI32(c.Golden)
	w.PutI32(c.Silver)
	w.PutI32(c.Honor)
	w.PutI32(c.Crystal)
	w.PutI32(c.PresentPoint)
}

// EncodeNotifyCharData builds message 1016 (CharMessage.NotifyCharData).
// Fields: m_charData(CHAR_BASIC), m_currency(CHAR_CURRENCY), m_queryUrl(utf8), m_technoVec(array<i32>)
func EncodeNotifyCharData(basic *CharBasic, currency *CharCurrency, queryUrl string, technoVec []int32) []byte {
	w := NewWriter()
	writeCharBasic(w, basic)
	writeCharCurrency(w, currency)
	w.PutUTF8(queryUrl)
	w.PutU16(uint16(len(technoVec)))
	for _, t := range technoVec {
		w.PutI32(t)
	}
	return BuildFrame(MsgNotifyCharData, 0, w.Bytes())
}

// EncodeNotifyCharCurrency builds message 1039 (CurrencyMessage.CharCurrencyAction).
// Fields: m_flow(u16), m_reason(u16), m_currency(CHAR_CURRENCY)
func EncodeNotifyCharCurrency(c *CharCurrency) []byte {
	w := NewWriter()
	w.PutU16(0)
	w.PutU16(0)
	writeCharCurrency(w, c)
	return BuildFrame(MsgNotifyCharCurrency, 0, w.Bytes())
}

// EncodeNotifyFirstCharge builds message 1031 (CharMessage.NotifyFirstCharge).
// Fields: m_nChargeCount(u32)
func EncodeNotifyFirstCharge(chargeCount uint32) []byte {
	w := NewWriter()
	w.PutU32(chargeCount)
	return BuildFrame(MsgNotifyFirstCharge, 0, w.Bytes())
}

// EncodeNotifyCharProtectInfo builds message 1033 (CharMessage.NotifyCharProtectInfo).
// Fields: m_bHasPwd(u8), m_nDelPwdTicket(u32)
func EncodeNotifyCharProtectInfo(hasPwd uint8, delPwdTicket uint32) []byte {
	w := NewWriter()
	w.PutU8(hasPwd)
	w.PutU32(delPwdTicket)
	return BuildFrame(MsgNotifyCharProtectInfo, 0, w.Bytes())
}

// EncodeNotifyTankList builds message 1150 (TankMessage.NotifyTankList).
// Fields: m_tankVec(array of TankInstance), m_notifyType(u8), m_contType(u8)
// For initial load: notifyType=1 (clear + load)
func EncodeNotifyTankList(notifyType, contType uint8, tanks []TankInstance) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(tanks)))
	for _, t := range tanks {
		writeTankInstance(w, &t)
	}
	w.PutU8(notifyType)
	w.PutU8(contType)
	return BuildFrame(MsgNotifyTankList, 0, w.Bytes())
}

// EncodeUpdateTankInstance builds message 1151 (TankMessage.UpdateTankInstance).
// Fields: m_tankInst (TankInstance), m_opType (u8)
func EncodeUpdateTankInstance(t *TankInstance, opType uint8) []byte {
	w := NewWriter()
	writeTankInstance(w, t)
	w.PutU8(opType)
	return BuildFrame(MsgNotifyTankUpdate, 0, w.Bytes())
}

type TankInstance struct {
	TankUuid        string
	TankID          uint32
	TankLevel       uint8
	TankExp         uint32
	ExtFlag         uint32
	StthLevel       uint8
	ExternalID      uint32
	WarCount        uint32
	WeekWarCount    uint32
	ContType        uint8
	CashHireCount   uint8
	CoinHireCount   uint8
	ExistTime       uint32
	HaloID          uint32
	SkinFrameType   uint8
	OwnTime         uint32
	StthCount       uint8
	ComSkillID      uint32
	CrystalSchemeID uint8
	TalPageUuid     string
	ProficiencyVal  uint32
	BattleGains     int32
}

func writeTankInstance(w *Writer, t *TankInstance) {
	w.PutUTF8(t.TankUuid)
	w.PutU32(t.TankID)
	w.PutU8(t.TankLevel)
	w.PutU32(t.TankExp)
	w.PutU32(t.ExtFlag)
	w.PutU8(t.StthLevel)
	w.PutU32(t.ExternalID)
	w.PutU32(t.WarCount)
	w.PutU32(t.WeekWarCount)
	w.PutU8(t.ContType)
	w.PutU8(t.CashHireCount)
	w.PutU8(t.CoinHireCount)
	w.PutU32(t.ExistTime)
	w.PutU32(t.HaloID)
	w.PutU8(t.SkinFrameType)
	w.PutU32(t.OwnTime)
	w.PutU8(t.StthCount)
	w.PutU32(t.ComSkillID)
	w.PutU8(t.CrystalSchemeID)
	w.PutUTF8(t.TalPageUuid)
	w.PutU32(t.ProficiencyVal)
	w.PutI32(t.BattleGains)
}

// EncodeNotifyItemList builds message 1100 (ItemMessage.NotifyItemList).
// Fields: m_contType(u32), m_itemVec(array of ITEM_INSTANCE), m_notifyType(u8)
// notifyType: 1 = replace all, 2 = add/update, 5 = put
func EncodeNotifyItemList(contType uint32, notifyType uint8, items []ItemInstance) []byte {
	w := NewWriter()
	w.PutU32(contType)
	w.PutU16(uint16(len(items)))
	for _, it := range items {
		writeItemInstance(w, &it)
	}
	w.PutU8(notifyType)
	return BuildFrame(MsgNotifyItemList, 0, w.Bytes())
}

// EncodeUpdateItemInstance builds message 1102 (ItemMessage.UpdateItemInstance).
func EncodeUpdateItemInstance(contType uint32, it *ItemInstance) []byte {
	w := NewWriter()
	w.PutU32(contType)
	writeItemInstance(w, it)
	return BuildFrame(MsgNotifyItemAdd, 0, w.Bytes())
}

type ItemInstance struct {
	ItemUuid   string
	TemplateID uint32
	LifeTime   uint32
	ExtFlag    uint32
	Count      int32
	Level      uint8
	UpLevel    uint8
	Exp        int32
	Rank       uint8
	UpCost     int32
	RankCost   int32
	CreateTime uint32
	SlotNo     int16
}

func writeItemInstance(w *Writer, it *ItemInstance) {
	w.PutUTF8(it.ItemUuid)
	w.PutU32(it.TemplateID)
	w.PutU32(it.LifeTime)
	w.PutU32(it.ExtFlag)
	w.PutI32(it.Count)
	w.PutU8(it.Level)
	w.PutU8(it.UpLevel)
	w.PutI32(it.Exp)
	w.PutU8(it.Rank)
	w.PutI32(it.UpCost)
	w.PutI32(it.RankCost)
	w.PutU32(it.CreateTime)
	w.PutI16(it.SlotNo)
}

// EncodeHeartBeat builds message 60 (SystemMessage.SystemHeartBeat).
func EncodeHeartBeat() []byte {
	return BuildFrame(MsgSystemHeartBeat, 0, nil)
}

// EncodePingResponse builds message 61 response with server timestamp.
func EncodePingResponse(clientMs uint32, serverMs uint32) []byte {
	w := NewWriter()
	w.PutU32(clientMs)
	w.PutU32(serverMs)
	return BuildFrame(MsgRequestPing, 0, w.Bytes())
}

// EncodeNotifySettingFlag builds message 1036.
// Fields: m_setting(u32)
func EncodeNotifySettingFlag(setting uint32) []byte {
	w := NewWriter()
	w.PutU32(setting)
	return BuildFrame(MsgNotifySettingFlag, 0, w.Bytes())
}

// EncodeNotifyBuyGoodsOk builds message 1041 (TradeMessage.NotifyBuyGoodsOk).
// Fields: m_type(i32), goods_id(u32)
func EncodeNotifyBuyGoodsOk(buyType int32, goodsID uint32) []byte {
	w := NewWriter()
	w.PutI32(buyType)
	w.PutU32(goodsID)
	return BuildFrame(MsgBuyGoodsResult, 0, w.Bytes())
}

// EncodeRejectGoodsBuy builds message 1042 (TradeMessage.RejectGoodsBuy).
func EncodeRejectGoodsBuy() []byte {
	return BuildFrame(MsgBuyGoodsFailed, 0, nil)
}

// EncodeNotifyFriendApplyList builds message 10002 (FriendMessage.NotifyFriendApplyList).
// Fields: m_applyList (Array with u16 length)
func EncodeNotifyFriendApplyList() []byte {
	w := NewWriter()
	w.PutU16(0) // 0 pending applications
	return BuildFrame(MsgNotifyFriendApplyList, 0, w.Bytes())
}

// EncodeNotifyFriendApplyCount builds message 10003 (FriendMessage.NotifyFriendApplyCount).
// Fields: m_applyCount (u8)
func EncodeNotifyFriendApplyCount(count uint8) []byte {
	w := NewWriter()
	w.PutU8(count)
	return BuildFrame(MsgNotifyFriendApplyCount, 0, w.Bytes())
}

// EncodeNotifyCityInfoInit builds message 1303.
func EncodeNotifyCityInfoInit() []byte {
	w := NewWriter()
	w.PutU16(0) // 0 cities
	return BuildFrame(MsgNotifyCityInfoInit, 0, w.Bytes())
}

// EncodeNotifyBossState builds message 1951.
func EncodeNotifyBossState(activityID int32, state int32) []byte {
	w := NewWriter()
	w.PutI32(activityID)
	w.PutI32(state) // 2: running, 3: closed
	w.PutU32(0)
	return BuildFrame(MsgNotifyBossState, 0, w.Bytes())
}

// EncodeNotifyBossSnapshot builds message 1952.
func EncodeNotifyBossSnapshot(activityID int32, hp int32, maxHP int32, harm int32, rank uint32) []byte {
	w := NewWriter()
	w.PutI32(activityID)
	w.PutI32(hp)
	w.PutI32(maxHP)
	w.PutI32(harm)
	w.PutU32(rank)
	w.PutU32(0) // enter_at
	w.PutU16(0) // 0 ranking rows
	return BuildFrame(MsgNotifyBossSnapshot, 0, w.Bytes())
}

// PlayerBriefData holds data for encoding a PLAYER_BRIEF.
type PlayerBriefData struct {
	AcctID   uint32
	CharUUID string
	Name     string
	Level    uint8
	AvatarID uint32
}

// EncodeNotifyPlayerList builds message 1703 with a list of online players.
func EncodeNotifyPlayerList(listType uint8, players []PlayerBriefData) []byte {
	w := NewWriter()
	w.PutU8(listType)
	w.PutU8(0) // page
	w.PutU16(uint16(len(players)))
	for _, p := range players {
		w.PutU32(p.AcctID)     // nAcctId
		w.PutUTF8(p.CharUUID) // szCharUuid
		w.PutUTF8(p.Name)     // szName
		w.PutU8(p.Level)      // bLevel
		w.PutU8(1)            // bSex
		w.PutU8(6)            // nVipLevel
		w.PutU8(1)            // eloSectionId
		w.PutU8(1)            // preEloSectionId
		w.PutU32(p.AvatarID)  // nAvatar
		w.PutU32(0)           // nDecorateId
		w.PutU16(0)           // nGraduate
		w.PutI16(1200)        // iElo
		w.PutU32(0)           // nHonorId
		w.PutU32(0)           // nBoosterAttack
		w.PutU32(0)           // nMilitaryStar
		w.PutU32(0)           // nTeamPlace
		w.PutUTF8("")         // szTeamName
	}
	return BuildFrame(MsgNotifyPlayerList, 0, w.Bytes())
}

// RoomInfoData holds the data needed to encode a RoomInfo struct.
type RoomInfoData struct {
	RoomID     uint32
	NumPlayers uint32
	MaxPlayers uint32
	MapID      uint32
	Mode       uint32
	State      uint8
	IsValidate uint8
	RoomType   uint8
	Name       string
	TeamID     uint32
}

// EncodeNotifyHallDisplayList builds message 1724.
func EncodeNotifyHallDisplayList(site int32, roomType uint8, rooms []RoomInfoData) []byte {
	w := NewWriter()
	// m_roomList: array of RoomInfo, length prefix u16
	w.PutU16(uint16(len(rooms)))
	for _, r := range rooms {
		w.PutU32(r.RoomID)
		w.PutU32(r.NumPlayers)
		w.PutU32(r.MaxPlayers)
		w.PutU32(r.MapID)
		w.PutU32(r.Mode)
		w.PutU8(r.State)
		w.PutU8(r.IsValidate)
		w.PutU8(r.RoomType)
		w.PutUTF8(r.Name)
		w.PutU32(r.TeamID)
	}
	w.PutU16(0) // 0 scenes
	w.PutI32(site)
	w.PutU8(roomType)
	return BuildFrame(MsgNotifyHallDisplayList, 0, w.Bytes())
}

// EncodeRoomCharBrief builds ROOM_CHAR_BRIEF for room members.
func EncodeRoomCharBrief(charID uint32, charUUID, name string, level uint8, avatarID uint32, activeTankID uint32, tankLevel uint8, externalID uint32, camp uint8) []byte {
	w := NewWriter()
	// ROOM_CHAR_BRIEF:
	w.PutU8(0) // bReady = 0 (not ready by default)
	w.PutU8(0) // bBattle = 0

	// CHAR_BRIEF -> 1. PLAYER_BRIEF:
	w.PutU32(charID)
	w.PutUTF8(charUUID)
	w.PutUTF8(name)
	w.PutU8(level)
	w.PutU8(1)        // bSex (1: male)
	w.PutU8(6)        // nVipLevel
	w.PutU8(1)        // eloSectionId
	w.PutU8(1)        // preEloSectionId
	w.PutU32(avatarID) // nAvatar
	w.PutU32(0)       // nDecorateId
	w.PutU16(0)       // nGraduate
	w.PutI16(1200)    // iElo
	w.PutU32(0)       // nHonorId
	w.PutU32(0)       // nBoosterAttack
	w.PutU32(0)       // nMilitaryStar
	w.PutU32(0)       // nTeamPlace
	w.PutUTF8("")     // szTeamName

	// 2. OTHER_BRIEF:
	w.PutU32(activeTankID)
	w.PutU8(tankLevel)
	w.PutU8(0)          // tryTank
	w.PutU32(0)         // btItemId
	w.PutU8(0)          // btRank
	w.PutU8(0)          // btLevel
	w.PutU8(0)          // btUpLevel
	w.PutU32(0)         // btUpCost
	w.PutU32(0)         // btRankCost
	w.PutU32(0)         // honorId
	w.PutU32(externalID) // tankExternal (0 if default skin)
	w.PutU32(0)         // haloId
	w.PutU8(0)          // skinFrameType
	w.PutU32(0)         // btAtk
	w.PutU32(0)         // tankPartScore
	w.PutU32(0)         // commandSkill
	w.PutU32(0)         // sprayId

	// CHAR_BRIEF trailing fields:
	w.PutU32(299001) // regionUid
	w.PutU32(0)      // nIp
	w.PutU8(camp)    // bCamp (1 = Camp A, 2 = Camp B)
	w.PutU16(0)      // buffVec len = 0

	return w.Bytes()
}

// EncodeEnterRoomOk builds message 1700 (RoomMessage.EnterRoomOk).
func EncodeEnterRoomOk(roomID, createID uint32, name string, roomType uint8, mode uint32, mapID uint32, password uint32, memberBriefs ...[]byte) []byte {
	w := NewWriter()
	w.PutU32(roomID)
	w.PutU32(createID)
	w.PutU8(10) // m_nMax
	w.PutU8(2)  // m_nMin
	w.PutU8(2)  // m_nObNum
	w.PutU32(password)
	w.PutUTF8(name)
	w.PutU8(0) // m_state (RST_WAIT)
	w.PutU8(roomType)
	w.PutU32(mode)

	// roomConfig: ROOM_CONFIG (8 bytes)
	w.PutU32(mapID)
	w.PutU8(0) // m_bBanRobot
	w.PutU8(0) // m_nTankAvailableLevel
	w.PutU8(0) // m_iLadderScetionMin
	w.PutU8(0) // m_iLadderScetionMax

	// charVec:
	w.PutU16(uint16(len(memberBriefs)))
	for _, mb := range memberBriefs {
		w.buf.Write(mb)
	}

	// observerVec:
	w.PutU16(0)

	return BuildFrame(MsgEnterRoomOk, 0, w.Bytes())
}

// EncodeNotifyRoomOp builds message 1701 (RoomMessage.NotifyRoomOp).
func EncodeNotifyRoomOp(roomOp uint8, startOID, target uint32) []byte {
	w := NewWriter()
	w.PutU8(roomOp)
	w.PutU32(startOID)
	w.PutU32(target)
	return BuildFrame(MsgNotifyRoomOp, 0, w.Bytes())
}

// EncodeNotifyRoomAdd builds message 1702 (RoomMessage.NotifyRoomAdd).
// Notifies existing room members that a new player joined.
// roomCharBrief is the pre-encoded ROOM_CHAR_BRIEF (from EncodeRoomCharBrief).
// We strip the first 2 bytes (bReady, bBattle) to get CHAR_BRIEF.
func EncodeNotifyRoomAdd(roomCharBrief []byte, isObserver uint8) []byte {
	w := NewWriter()
	// CHAR_BRIEF = ROOM_CHAR_BRIEF without first 2 bytes (bReady, bBattle)
	if len(roomCharBrief) > 2 {
		w.buf.Write(roomCharBrief[2:])
	}
	w.PutU8(isObserver)
	return BuildFrame(MsgNotifyRoomAdd, 0, w.Bytes())
}

// EncodeNotifyStartMatch builds message 1719 (RoomMessage.NotifyStartMatch).
// Client reads raw 13 bytes:
//   offset 0: u32 m_nPairTime  – seconds already waited
//   offset 4: u8  m_type       – room/match type
//   offset 5: u32 m_nAvgTime   – average wait time (seconds)
//   offset 9: u32 m_nCount     – number of players in queue
func EncodeNotifyStartMatch(pairTime uint32, matchType uint8, avgTime uint32, count uint32) []byte {
	w := NewWriter()
	w.PutU32(pairTime)
	w.PutU8(matchType)
	w.PutU32(avgTime)
	w.PutU32(count)
	return BuildFrame(MsgNotifyStartMatch, 0, w.Bytes())
}

// EncodeNotifyStopMatch builds message 1720 (RoomMessage.NotifyStopMatch).
// Empty body – client just clears the pairing state.
func EncodeNotifyStopMatch() []byte {
	return BuildFrame(MsgNotifyStopMatch, 0, nil)
}

// EncodeNotifyRoomMap builds message 1704 (RoomMessage.NotifyRoomMap).
// Body: u32 m_nMapId
func EncodeNotifyRoomMap(mapID uint32) []byte {
	w := NewWriter()
	w.PutU32(mapID)
	return BuildFrame(MsgNotifyRoomMap, 0, w.Bytes())
}

// EncodeNotifyTankSelected builds message 1727 (SceneMessage.NotifyTankSelected).
func EncodeNotifyTankSelected(charOID, tankID, tankCont, tankExt, skinFrameType, commandSkill uint32) []byte {
	w := NewWriter()
	w.PutU32(charOID)
	w.PutU32(tankID)
	w.PutU32(tankCont)
	w.PutU32(tankExt)
	w.PutU32(skinFrameType)
	w.PutU32(commandSkill)
	return BuildFrame(MsgNotifyTankSelect, 0, w.Bytes())
}

// EncodeNotifyStartGame builds message 1705 (RoomMessage.NotifyStartGame).
func EncodeNotifyStartGame(sceneID, mapID uint32, roomType uint8, charBriefs [][]byte, enterType uint8) []byte {
	w := NewWriter()
	w.PutU32(sceneID)
	w.PutU32(mapID)
	w.PutU8(roomType)

	// m_charData: array of CHAR_BRIEF
	w.PutU16(uint16(len(charBriefs)))
	for _, cb := range charBriefs {
		if len(cb) > 2 {
			w.buf.Write(cb[2:])
		} else {
			w.buf.Write(cb)
		}
	}

	// m_backData: empty array of u32
	w.PutU16(0)

	// m_bEnterType: 0 (player)
	w.PutU8(enterType)

	return BuildFrame(MsgNotifyStartGame, 0, w.Bytes())
}

// EncodeNotifyLoadedRate builds message 1709 (RoomMessage.NotifyLoadedRate).
func EncodeNotifyLoadedRate(tankID, delay, loaded uint32) []byte {
	w := NewWriter()
	w.PutU32(tankID)
	w.PutU32(delay)
	w.PutU32(loaded)
	return BuildFrame(MsgNotifyLoadedRate, 0, w.Bytes())
}

// TankBattleInfo holds data to encode a TankMessage.TankInfo struct.
type TankBattleInfo struct {
	ObjID       uint32
	AcctOid     uint32
	X           int16
	Y           int16
	HP          int32
	MaxHP       int32
	Star        uint8
	Camp        uint8
	Name        string
	LifeCount   int16
	BattleExp   uint32
	BattleLevel uint8
	TankLevel   uint8
	MP           int32
	MaxMP        int32
	Shield       int32
	FireRate     int16
	MoveSpeed    int16
	NormalBullet uint32
	Skills       [4]uint32
}

func putTankInfo(w *Writer, t *TankBattleInfo) {
	w.PutU32(t.ObjID)
	w.PutU32(t.AcctOid)
	w.PutI16(t.X)
	w.PutI16(t.Y)
	w.PutI32(t.HP)
	w.PutI32(t.MaxHP)
	w.PutU8(t.Star)
	w.PutU8(t.Camp)
	w.PutUTF8(t.Name)
	w.PutU16(0) // m_buffVec: empty array
	w.PutI16(t.LifeCount)
	w.PutU32(t.BattleExp)
	w.PutU8(t.BattleLevel)
	w.PutU8(t.TankLevel)
	w.PutI32(t.MP)
	w.PutI32(t.MaxMP)
	w.PutI32(t.Shield)
}

// EncodeNotifySelfData builds message 1550 (TankMessage.NotifySelfData).
func EncodeNotifySelfData(self *TankBattleInfo) []byte {
	w := NewWriter()
	putTankInfo(w, self)

	fireRate := self.FireRate
	if fireRate <= 0 {
		fireRate = 500
	}
	moveSpeed := self.MoveSpeed
	if moveSpeed <= 0 {
		moveSpeed = 200
	}
	w.PutI16(fireRate)  // m_fireRate
	w.PutI16(moveSpeed) // m_speed

	// m_skillVec: PropsInfo array (slot 0 = normal shot, slot 1 = E, slot 2 = Space, slot 3 = R)
	var slots []struct {
		slotNo  uint8
		propsID uint32
	}
	normalBullet := self.NormalBullet
	if normalBullet == 0 {
		normalBullet = 1
	}
	slots = append(slots, struct {
		slotNo  uint8
		propsID uint32
	}{0, normalBullet}) // Slot 0: normal shot

	skillE := self.Skills[0]
	if skillE == 0 {
		skillE = 1001
	}
	slots = append(slots, struct {
		slotNo  uint8
		propsID uint32
	}{1, skillE})

	skillSpace := self.Skills[1]
	if skillSpace == 0 {
		skillSpace = 1002
	}
	slots = append(slots, struct {
		slotNo  uint8
		propsID uint32
	}{2, skillSpace})

	skillR := self.Skills[3]
	if skillR != 0 {
		slots = append(slots, struct {
			slotNo  uint8
			propsID uint32
		}{10, skillR}) // Slot 10: R skill (client uses slot 10 for the R button, not slot 3)
	}

	w.PutU16(uint16(len(slots)))
	for _, s := range slots {
		w.PutU32(s.propsID) // nPropsId
		w.PutU8(s.slotNo)   // bSlotno
		w.PutI8(-1)         // iCount = -1 (unlimited)
		w.PutU64Words(0, 0) // nEndTime
		w.PutU64Words(0, 0) // nCountCoolTime
	}

	w.PutU16(0) // m_itemVec: empty
	w.PutU8(0)  // m_nKillCount
	w.PutU8(0)  // m_nDeadCount
	w.PutU8(0)  // m_nAssistCount
	return BuildFrame(MsgNotifySelfData, 0, w.Bytes())
}

// EncodeNotifyOtherList builds message 1551 (TankMessage.NotifyOtherList).
func EncodeNotifyOtherList(others []*TankBattleInfo) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(others)))
	for _, t := range others {
		putTankInfo(w, t)
	}
	return BuildFrame(MsgNotifyOtherList, 0, w.Bytes())
}

// EncodeNotifyBattleEnter builds message 1586 (SceneMessage.NotifyBattleEnter).
func EncodeNotifyBattleEnter(startTime uint32, overTime uint8) []byte {
	w := NewWriter()
	w.PutU32(startTime)
	w.PutU8(overTime)
	return BuildFrame(MsgNotifyBattleEnter, 0, w.Bytes())
}

// EncodeNotifyStopMove builds message 1554 (SceneMessage.NotifyStopMove).
// Halts actor motion immediately and snaps position (used for blinks / instant displacement).
func EncodeNotifyStopMove(sceneID, objID uint32, x, y int16) []byte {
	w := NewWriter()
	w.PutU32(sceneID)
	w.PutU32(objID)
	w.PutI16(x)
	w.PutI16(y)
	return BuildFrame(MsgNotifyStopMove, 0, w.Bytes())
}

// EncodeSyncSceneMove builds message 1564 (SceneMessage.SyncSceneData) with a single MoveInfo.
func EncodeSyncSceneMove(objID uint32, x, y, speed int16, direction, moveType uint8) []byte {
	w := NewWriter()
	// 1. m_moveVec (len = 1)
	w.PutU16(1)
	w.PutU32(objID)
	w.PutI16(x)
	w.PutI16(y)
	w.PutI16(speed)
	w.PutU8(direction)
	w.PutU8(moveType)

	// 2..10: empty vectors
	w.PutU16(0) // m_fireVec
	w.PutU16(0) // m_skillVec
	w.PutU16(0) // m_hpVec
	w.PutU16(0) // m_deadVec
	w.PutU16(0) // m_mpVec
	w.PutU16(0) // m_blowUpVec
	w.PutU16(0) // m_delVec
	w.PutU16(0) // m_overVec
	w.PutU16(0) // m_shieldVec

	return BuildFrame(MsgSyncSceneData, 0, w.Bytes())
}

// EncodeSyncSceneFire builds message 1564 (SceneMessage.SyncSceneData) with a single NotifyFire.
func EncodeSyncSceneFire(bulletID, shooterID uint32, startX, startY, destX, destY, speed int16, template uint32) []byte {
	w := NewWriter()
	// 1. m_moveVec (len = 0)
	w.PutU16(0)

	// 2. m_fireVec (len = 1)
	w.PutU16(1)
	w.PutU32(bulletID)
	w.PutU32(shooterID)
	w.PutI16(startX)
	w.PutI16(startY)
	w.PutI16(destX)
	w.PutI16(destY)
	w.PutI16(speed)
	w.PutU32(template)

	// 3..10: empty vectors
	w.PutU16(0) // m_skillVec
	w.PutU16(0) // m_hpVec
	w.PutU16(0) // m_deadVec
	w.PutU16(0) // m_mpVec
	w.PutU16(0) // m_blowUpVec
	w.PutU16(0) // m_delVec
	w.PutU16(0) // m_overVec
	w.PutU16(0) // m_shieldVec

	return BuildFrame(MsgSyncSceneData, 0, w.Bytes())
}

// EncodeSyncSceneSkill builds message 1564 (SceneMessage.SyncSceneData) with a single NotifySkill.
func EncodeSyncSceneSkill(ownerID, targetID, skillID uint32, startX, startY, destX, destY int16, ready uint8) []byte {
	w := NewWriter()
	w.PutU16(0) // 1. m_moveVec
	w.PutU16(0) // 2. m_fireVec

	// 3. m_skillVec (len = 1)
	w.PutU16(1)
	w.PutU32(ownerID)
	w.PutU32(targetID)
	w.PutU32(skillID)
	w.PutI16(startX)
	w.PutI16(startY)
	w.PutI16(destX)
	w.PutI16(destY)
	w.PutU8(ready)
	w.PutU8(1) // count

	// 4..10: empty vectors
	w.PutU16(0) // m_hpVec
	w.PutU16(0) // m_deadVec
	w.PutU16(0) // m_mpVec
	w.PutU16(0) // m_blowUpVec
	w.PutU16(0) // m_delVec
	w.PutU16(0) // m_overVec
	w.PutU16(0) // m_shieldVec

	return BuildFrame(MsgSyncSceneData, 0, w.Bytes())
}

// EncodeSyncSceneExpiredBullet builds message 1564 with a single entry in the expired_bullets vector.
// Used to remove scene objects (Wukong space visuals, etc.) after their lifetime expires.
func EncodeSyncSceneExpiredBullet(objectID uint32) []byte {
	w := NewWriter()
	w.PutU16(0) // 1. m_moveVec
	w.PutU16(0) // 2. m_fireVec
	w.PutU16(0) // 3. m_skillVec
	w.PutU16(0) // 4. m_hpVec
	w.PutU16(0) // 5. m_deadVec
	w.PutU16(0) // 6. m_mpVec
	w.PutU16(0) // 7. m_blowUpVec
	w.PutU16(0) // 8. m_delVec
	// 9. m_overVec (expired_bullets) - len = 1
	w.PutU16(1)
	w.PutU32(objectID)
	w.PutU16(0) // 10. m_shieldVec
	return BuildFrame(MsgSyncSceneData, 0, w.Bytes())
}

// EncodeNotifySkillCooldown builds message 1572 (PropsInfo + m_nOwnerId) to start skill cooldown on client.
func EncodeNotifySkillCooldown(ownerID, skillID uint32, slotNo uint8, endTimeMS uint64) []byte {
	w := NewWriter()
	w.PutU32(skillID)
	w.PutU8(slotNo)
	w.PutI8(-1) // iCount = -1 (unlimited)
	w.PutU64Words(uint32(endTimeMS&0xFFFFFFFF), uint32(endTimeMS>>32))
	w.PutU64Words(0, 0) // nCountCoolTime
	w.PutU32(ownerID)
	return BuildFrame(MsgNotifySkillCoolTime, 0, w.Bytes())
}

// EncodeNotifySwapSkill builds message 1579 to swap a skill slot's active template (e.g. empowered basic attack).
func EncodeNotifySwapSkill(skillID uint32, slotNo uint8, endTimeMS uint64) []byte {
	w := NewWriter()
	w.PutU32(skillID)
	w.PutU8(slotNo)
	w.PutI8(-1)
	w.PutU64Words(uint32(endTimeMS&0xFFFFFFFF), uint32(endTimeMS>>32))
	w.PutU64Words(0, 0)
	return BuildFrame(MsgNotifySwapSkill, 0, w.Bytes())
}

// EncodeNotifyAddBuff builds message 1558 (targetID, buffTemplateID, instID, stacks, casterID, existTimeMS).
func EncodeNotifyAddBuff(targetID, templateID, instID uint32, stacks uint8, casterID, durationMS uint32) []byte {
	w := NewWriter()
	w.PutU32(targetID)
	w.PutU32(templateID)
	w.PutU32(instID)
	w.PutU8(stacks)
	w.PutU32(casterID)
	w.PutU32(durationMS)
	return BuildFrame(MsgNotifyAddBuff, 0, w.Bytes())
}

// EncodeNotifyRemoveBuff builds message 1559 (targetID, buffInstID).
func EncodeNotifyRemoveBuff(targetID, instID uint32) []byte {
	w := NewWriter()
	w.PutU32(targetID)
	w.PutU32(instID)
	return BuildFrame(MsgNotifyRemoveBuff, 0, w.Bytes())
}

// EncodeNotifyAttrChange builds message 1560 (acctOid, updateType, updateVal).
// updateType: 1=speed, 3=maxHp, 4=fireIntervalMS, 5=lives, 7=hp, 8=maxMp.
func EncodeNotifyAttrChange(acctID uint32, updateType uint8, val int32) []byte {
	w := NewWriter()
	w.PutU32(acctID)
	w.PutU8(updateType)
	w.PutI32(val)
	return BuildFrame(MsgNotifyAttrChange, 0, w.Bytes())
}

// EncodeNotifyBuffUpdate builds message 1581 (instID, existTimeMS, stacks).
func EncodeNotifyBuffUpdate(instID, durationMS uint32, stacks uint8) []byte {
	w := NewWriter()
	w.PutU32(instID)
	w.PutU32(durationMS)
	w.PutU8(stacks)
	return BuildFrame(MsgNotifyBuffUpdate, 0, w.Bytes())
}

// EncodeAddObject builds message 1556 (NotifyAddObject).
// Schema: m_nSceneId(u32) + ObjInfo{m_objId(u32), m_tplId(u32), m_x(i16), m_y(i16),
//   m_hp(i32), m_bCamp(u8), m_maxHp(i32), m_ownerId(u32), m_shield(i32), m_buffVec(u16 len=0)}
func EncodeAddObject(sceneID, objectID, templateID uint32, x, y int16, camp uint8, ownerID uint32) []byte {
	w := NewWriter()
	w.PutU32(sceneID)    // m_nSceneId
	w.PutU32(objectID)   // m_objId
	w.PutU32(templateID) // m_tplId
	w.PutI16(x)          // m_x
	w.PutI16(y)          // m_y
	w.PutI32(0)          // m_hp
	w.PutU8(camp)        // m_bCamp
	w.PutI32(0)          // m_maxHp
	w.PutU32(ownerID)    // m_ownerId
	w.PutI32(0)          // m_shield
	w.PutU16(0)          // m_buffVec (empty array)
	return BuildFrame(MsgNotifyAddObject, 0, w.Bytes())
}

// EncodeAddDrop builds message 1556 for a map pickup/drop (hp=1, maxHp=1, ownerId=1).
func EncodeAddDrop(sceneID, dropID, templateID uint32, x, y int16) []byte {
	w := NewWriter()
	w.PutU32(sceneID)
	w.PutU32(dropID)
	w.PutU32(templateID)
	w.PutI16(x)
	w.PutI16(y)
	w.PutI32(1) // m_hp
	w.PutU8(0)  // m_bCamp
	w.PutI32(1) // m_maxHp
	w.PutU32(1) // m_ownerId
	w.PutI32(0) // m_shield
	w.PutU16(0) // m_buffVec
	return BuildFrame(MsgNotifyAddObject, 0, w.Bytes())
}

// EncodeSyncSceneDel builds message 1564 with m_delVec entries (removed map objects/drops).
func EncodeSyncSceneDel(removedIDs []uint32) []byte {
	w := NewWriter()
	w.PutU16(0) // 1. m_moveVec
	w.PutU16(0) // 2. m_fireVec
	w.PutU16(0) // 3. m_skillVec
	w.PutU16(0) // 4. m_hpVec
	w.PutU16(0) // 5. m_deadVec
	w.PutU16(0) // 6. m_mpVec
	w.PutU16(0) // 7. m_blowUpVec
	// 8. m_delVec
	w.PutU16(uint16(len(removedIDs)))
	for _, id := range removedIDs {
		w.PutU32(id)
	}
	w.PutU16(0) // 9. m_overVec
	w.PutU16(0) // 10. m_shieldVec
	return BuildFrame(MsgSyncSceneData, 0, w.Bytes())
}


// EncodeSyncSceneHP builds message 1564 with m_hpVec entries.
// Each entry: u32 objID + i32 hp (current HP, not delta).
func EncodeSyncSceneHP(hpChanges []struct{ ObjID uint32; HP int32 }) []byte {
	w := NewWriter()
	w.PutU16(0) // 1. m_moveVec
	w.PutU16(0) // 2. m_fireVec
	w.PutU16(0) // 3. m_skillVec
	// 4. m_hpVec
	w.PutU16(uint16(len(hpChanges)))
	for _, hp := range hpChanges {
		w.PutU32(hp.ObjID)
		w.PutI32(hp.HP)
	}
	w.PutU16(0) // 5. m_deadVec
	w.PutU16(0) // 6. m_mpVec
	w.PutU16(0) // 7. m_blowUpVec
	w.PutU16(0) // 8. m_delVec
	w.PutU16(0) // 9. m_overVec
	w.PutU16(0) // 10. m_shieldVec
	return BuildFrame(MsgSyncSceneData, 0, w.Bytes())
}

// EncodeSyncSceneMP builds message 1564 with m_mpVec entries.
// Each entry: u32 objID + i32 mp (current MP).
func EncodeSyncSceneMP(mpChanges []struct{ ObjID uint32; MP int32 }) []byte {
	w := NewWriter()
	w.PutU16(0) // 1. m_moveVec
	w.PutU16(0) // 2. m_fireVec
	w.PutU16(0) // 3. m_skillVec
	w.PutU16(0) // 4. m_hpVec
	w.PutU16(0) // 5. m_deadVec
	// 6. m_mpVec
	w.PutU16(uint16(len(mpChanges)))
	for _, mp := range mpChanges {
		w.PutU32(mp.ObjID)
		w.PutI32(mp.MP)
	}
	w.PutU16(0) // 7. m_blowUpVec
	w.PutU16(0) // 8. m_delVec
	w.PutU16(0) // 9. m_overVec
	w.PutU16(0) // 10. m_shieldVec
	return BuildFrame(MsgSyncSceneData, 0, w.Bytes())
}

// EncodeSyncSceneBlown builds message 1564 with m_blowUpVec + m_hpVec + m_deadVec.
// Combined packet for bullet-hit events.
func EncodeSyncSceneCombat(
	hpChanges []struct{ ObjID uint32; HP int32 },
	deaths []struct{ ObjID uint32; X, Y int16 },
	blownBullets []uint32,
	expired []uint32,
) []byte {
	w := NewWriter()
	w.PutU16(0) // 1. m_moveVec
	w.PutU16(0) // 2. m_fireVec
	w.PutU16(0) // 3. m_skillVec

	// 4. m_hpVec
	w.PutU16(uint16(len(hpChanges)))
	for _, hp := range hpChanges {
		w.PutU32(hp.ObjID)
		w.PutI32(hp.HP)
	}

	// 5. m_deadVec — struct AINpcDead: u32 m_AINpcId, i16 m_x, i16 m_y
	w.PutU16(uint16(len(deaths)))
	for _, d := range deaths {
		w.PutU32(d.ObjID)
		w.PutI16(d.X)
		w.PutI16(d.Y)
	}

	w.PutU16(0) // 6. m_mpVec

	// 7. m_blowUpVec
	w.PutU16(uint16(len(blownBullets)))
	for _, b := range blownBullets {
		w.PutU32(b)
	}

	w.PutU16(0) // 8. m_delVec

	// 9. m_overVec (expired bullets)
	w.PutU16(uint16(len(expired)))
	for _, e := range expired {
		w.PutU32(e)
	}

	w.PutU16(0) // 10. m_shieldVec
	return BuildFrame(MsgSyncSceneData, 0, w.Bytes())
}

// EncodeNotifyRespawnTimer builds message 1553.
// Fields: m_nAcctId(u32), m_nDelayMs(i32)
func EncodeNotifyRespawnTimer(acctID uint32, delayMS int32) []byte {
	w := NewWriter()
	w.PutU32(acctID)
	w.PutI32(delayMS)
	return BuildFrame(MsgNotifyRespawnTimer, 0, w.Bytes())
}

// EncodeNotifyKillInfo builds message 1566.
// Fields: killer(u32), victim(u32), skill(u32), x(i16), y(i16), multi(u8), streak(u8), dead_streak(u8), first_blood(u8), assist_count(u16), assists([]u32)
func EncodeNotifyKillInfo(killerID, victimID, skillTpl uint32, x, y int16) []byte {
	w := NewWriter()
	w.PutU32(killerID)
	w.PutU32(victimID)
	w.PutU32(skillTpl)
	w.PutI16(x)
	w.PutI16(y)
	w.PutU8(0) // multi kill
	w.PutU8(0) // streak
	w.PutU8(0) // dead streak
	w.PutU8(0) // first blood
	w.PutU16(0) // assist count
	return BuildFrame(MsgNotifyKillInfo, 0, w.Bytes())
}

// EncodeNotifyBorn builds message 1552 (NotifyAddTank — respawn).
// Client expects m_selfData = full TankInfo struct (same as 1550).
func EncodeNotifyBorn(tank *TankBattleInfo) []byte {
	w := NewWriter()
	putTankInfo(w, tank)
	return BuildFrame(MsgNotifyBorn, 0, w.Bytes())
}

// HpDelta holds one entry for SyncHpChange (msg 1605).
type HpDelta struct {
	ObjID    uint32
	Delta    int32  // negative = damage, positive = heal
	Fury     uint8  // >0 = crit
	CasterID uint32 // who caused the change
}

// EncodeSyncHpChange builds message 1605 (SceneMessage.SyncHpChange).
// Schema: m_hpChgInfoVec: array[u16 length] of HpChangeInfo { u32 m_objId, i32 m_objHp, u8 m_nFury, u32 m_casterId }
func EncodeSyncHpChange(deltas []HpDelta) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(deltas)))
	for _, d := range deltas {
		w.PutU32(d.ObjID)
		w.PutI32(d.Delta)
		w.PutU8(d.Fury)
		w.PutU32(d.CasterID)
	}
	return BuildFrame(MsgSyncHpChange, 0, w.Bytes())
}

// EncodeSyncSceneCombatEx builds message 1564 with hpVec + deadVec + blowUpVec + overVec + shieldVec.
func EncodeSyncSceneCombatEx(
	hpChanges []struct{ ObjID uint32; HP int32 },
	deaths []struct{ ObjID uint32; X, Y int16 },
	blownBullets []uint32,
	expired []uint32,
	shields []struct{ ObjID uint32; Shield int32 },
) []byte {
	w := NewWriter()
	w.PutU16(0) // 1. m_moveVec
	w.PutU16(0) // 2. m_fireVec
	w.PutU16(0) // 3. m_skillVec

	// 4. m_hpVec
	w.PutU16(uint16(len(hpChanges)))
	for _, hp := range hpChanges {
		w.PutU32(hp.ObjID)
		w.PutI32(hp.HP)
	}

	// 5. m_deadVec
	w.PutU16(uint16(len(deaths)))
	for _, d := range deaths {
		w.PutU32(d.ObjID)
		w.PutI16(d.X)
		w.PutI16(d.Y)
	}

	w.PutU16(0) // 6. m_mpVec

	// 7. m_blowUpVec
	w.PutU16(uint16(len(blownBullets)))
	for _, b := range blownBullets {
		w.PutU32(b)
	}

	w.PutU16(0) // 8. m_delVec

	// 9. m_overVec (expired bullets)
	w.PutU16(uint16(len(expired)))
	for _, e := range expired {
		w.PutU32(e)
	}

	// 10. m_shieldVec
	w.PutU16(uint16(len(shields)))
	for _, s := range shields {
		w.PutU32(s.ObjID)
		w.PutI32(s.Shield)
	}

	return BuildFrame(MsgSyncSceneData, 0, w.Bytes())
}

// EncodeNotifySettlement builds message 1708 (NotifyBattleEnd).
// Schema: m_nSceneId(u32), m_nMapId(u32), m_battleTime(u32), m_roomType(u8),
//   m_winCamp(u8), m_winType(u8), m_rebLifeCount(i16), m_buleLifeCount(i16),
//   m_tankVec(array[u16] of TankSettleInfo), m_escapeVec(array[u16] of TankSettleInfo),
//   m_svrExpRate(f32), m_tokengoldRate(f32), m_bpvpActOpen(u8), m_nItemDropRate(u32),
//   m_nKiller(u32), m_nAssister(u32), m_nKDA(u32), m_nDestroyer(u32),
//   m_nVictoryMvp(u32), m_nDefeatMvp(u32), m_sceneUuid(utf8)
func EncodeNotifySettlement(sceneID, mapID uint32, elapsedMS int32, roomType, winner, winType uint8, scores [3]int32, players []SettlementPlayer, honors HonorAwards) []byte {
	w := NewWriter()
	w.PutU32(sceneID)                 // m_nSceneId
	w.PutU32(mapID)                   // m_nMapId
	w.PutU32(uint32(elapsedMS / 1000)) // m_battleTime (seconds)
	w.PutU8(roomType)                 // m_roomType
	w.PutU8(winner)                   // m_winCamp (0=draw, 1=camp1, 2=camp2)
	w.PutU8(winType)                  // m_winType (1=normal, 3=surrender, 4=draw)
	w.PutI16(int16(scores[1]))        // m_rebLifeCount (red kills)
	w.PutI16(int16(scores[2]))        // m_buleLifeCount (blue kills)

	// m_tankVec: array[u16] of TankSettleInfo
	w.PutU16(uint16(len(players)))
	for _, p := range players {
		putTankSettleInfo(w, &p, winner)
	}

	// m_escapeVec: empty array
	w.PutU16(0)

	// m_svrExpRate, m_tokengoldRate
	w.PutF32(1.0) // m_svrExpRate
	w.PutF32(1.0) // m_tokengoldRate

	w.PutU8(0)  // m_bpvpActOpen
	w.PutU32(0) // m_nItemDropRate
	w.PutU32(honors.Killer)     // m_nKiller
	w.PutU32(honors.Assister)   // m_nAssister
	w.PutU32(honors.KDA)        // m_nKDA (MVP)
	w.PutU32(honors.Destroyer)  // m_nDestroyer
	w.PutU32(honors.VictoryMvp) // m_nVictoryMvp
	w.PutU32(honors.DefeatMvp)  // m_nDefeatMvp

	// m_sceneUuid (utf8 = u16 length + bytes)
	w.PutU16(0) // empty string

	return BuildFrame(MsgNotifySettlement, 0, w.Bytes())
}

// putTankSettleInfo writes one TankSettleInfo struct.
// Schema: m_charOid(u32), m_tankTpltId(u32), m_iStatData(array[u16] of i32),
//   m_iTeamMerit(i16), m_iOldElo(i16), m_iNewElo(i16), m_iTankGains(i16),
//   m_iNewTankGains(i32), m_bAward(u8), m_isWin(u8), m_iRobotType(u8),
//   m_eloSectionId(u8), m_battleLevel(u8), m_roomCount(u8), m_camp(u8),
//   m_expVec(array[u16] of SettleGroup), m_coinVec(array[u16] of SettleGroup),
//   m_tankExpVec(array[u16] of SettleGroup), m_itemVec(array[u16] of GiveItemStruct),
//   m_evalPve(PVE_Evaluation_Result: 5x u8)
func putTankSettleInfo(w *Writer, p *SettlementPlayer, winner uint8) {
	w.PutU32(p.AcctID)  // m_charOid
	w.PutU32(p.TankID)  // m_tankTpltId

	// m_iStatData: array of i32
	// [0]=deaths, [1]=kills, [2]=score, [3]=assists, [4]=0, [5]=0, [6]=damage
	statData := []int32{p.Deaths, p.Kills, p.Kills, p.Assists, 0, 0, p.Damage}
	w.PutU16(uint16(len(statData)))
	for _, v := range statData {
		w.PutI32(v)
	}

	w.PutI16(0) // m_iTeamMerit
	w.PutI16(0) // m_iOldElo
	w.PutI16(0) // m_iNewElo
	w.PutI16(0) // m_iTankGains
	w.PutI32(0) // m_iNewTankGains
	w.PutU8(0)  // m_bAward

	var isWin uint8
	if p.Camp == winner {
		isWin = 1
	}
	w.PutU8(isWin) // m_isWin

	w.PutU8(0) // m_iRobotType
	w.PutU8(0) // m_eloSectionId
	w.PutU8(1) // m_battleLevel
	w.PutU8(1) // m_roomCount
	w.PutU8(p.Camp) // m_camp

	// m_expVec, m_coinVec, m_tankExpVec: empty arrays
	w.PutU16(0) // m_expVec
	w.PutU16(0) // m_coinVec
	w.PutU16(0) // m_tankExpVec

	// m_itemVec: empty array
	w.PutU16(0)

	// m_evalPve: PVE_Evaluation_Result (5x u8)
	w.PutU8(0) // m_iTotalEval
	w.PutU8(0) // m_iHarmEval
	w.PutU8(0) // m_iDeadEval
	w.PutU8(0) // m_iTimeEval
	w.PutU8(0) // m_iBoosterEval
}

// HonorAwards holds end-of-match honor player IDs (account IDs).
type HonorAwards struct {
	Killer     uint32 // best kills
	Assister   uint32 // best assists
	KDA        uint32 // best (kills+assists)/deaths ratio (MVP)
	Destroyer  uint32 // most structure damage
	VictoryMvp uint32 // winning team MVP
	DefeatMvp  uint32 // losing team MVP
}

// SettlementPlayer holds per-player end-of-match stats.
type SettlementPlayer struct {
	AcctID  uint32
	Kills   int32
	Deaths  int32
	Assists int32
	Damage  int32
	Camp    uint8
	TankID  uint32
	MVP     uint8
}

// EncodeNotifyCampKillNum builds message 1710 (NotifyCampKillNum).
// Schema: m_nRedKill(i32), m_nBlueKill(i32)
func EncodeNotifyCampKillNum(redKills, blueKills int32) []byte {
	w := NewWriter()
	w.PutI32(redKills)
	w.PutI32(blueKills)
	return BuildFrame(MsgNotifyCampKillNum, 0, w.Bytes())
}

// EncodeNotifyExitBattle builds message 1707 (SceneMessage.NotifyExitBattle).
// Schema: m_nErrId(u32), m_nSceneId(u32), m_nCharId(u32), m_exitType(u32), m_isLook(u32)
func EncodeNotifyExitBattle(errID, sceneID, charID, exitType, isLook uint32) []byte {
	w := NewWriter()
	w.PutU32(errID)
	w.PutU32(sceneID)
	w.PutU32(charID)
	w.PutU32(exitType)
	w.PutU32(isLook)
	return BuildFrame(MsgNotifyExitBattle, 0, w.Bytes())
}

// OccupyFlagWire holds a single flag entry for msg 1565.
type OccupyFlagWire struct {
	Index     int32
	Camp      int32
	Locked    int32
	Progress  int32
	ScoreTime uint32
}

// EncodeNotifyOccupyState builds message 1565 (flag capture snapshot).
func EncodeNotifyOccupyState(flags []OccupyFlagWire) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(flags)))
	for _, f := range flags {
		w.PutI32(f.Index)
		w.PutI32(f.Camp)
		w.PutI32(f.Locked)
		w.PutI32(f.Progress)
		w.PutU32(f.ScoreTime)
	}
	return BuildFrame(MsgNotifyOccupyState, 0, w.Bytes())
}

// EncodeNotifyOccupyScore builds message 1732 (flag score increment).
func EncodeNotifyOccupyScore(index, camp, gain int32) []byte {
	w := NewWriter()
	w.PutI32(index)
	w.PutI32(camp)
	w.PutI32(gain)
	return BuildFrame(MsgNotifyOccupyScore, 0, w.Bytes())
}

// EncodeNotifyShowSurrenderVotation builds message 1597 (show vote panel to team).
// Schema: m_validCount(u8), m_nShowEndTime(u32), m_nNextTime(u32), m_nSponsor(u32)
func EncodeNotifyShowSurrenderVotation(validCount uint8, showEndTime, nextTime, sponsor uint32) []byte {
	w := NewWriter()
	w.PutU8(validCount)      // number of eligible voters
	w.PutU32(showEndTime)    // server time when vote popup ends (seconds since battle start)
	w.PutU32(nextTime)       // earliest next vote allowed (seconds since battle start)
	w.PutU32(sponsor)        // charID who initiated the vote
	return BuildFrame(MsgNotifyShowSurrenderVotation, 0, w.Bytes())
}

// EncodeUpdateVotationInfo builds message 1598 (update vote results).
// Schema: m_validCount(u8), m_vecVoteInfo(array[u16] of u8)
// Each vote value: 0=not voted, 1=deny, 2=agree, 3=invalid/absent
func EncodeUpdateVotationInfo(validCount uint8, votes []uint8) []byte {
	w := NewWriter()
	w.PutU8(validCount) // number of eligible voters
	w.PutU16(uint16(len(votes)))
	for _, v := range votes {
		w.PutU8(v)
	}
	return BuildFrame(MsgUpdateVotationInfo, 0, w.Bytes())
}

// EncodeNotifySurrenderVotationCoolTime builds message 1599 (vote cooldown).
// Schema: m_nTime(u32)
func EncodeNotifySurrenderVotationCoolTime(coolTime uint32) []byte {
	w := NewWriter()
	w.PutU32(coolTime) // seconds since battle start when cooldown ends
	return BuildFrame(MsgNotifySurrenderVotationCoolTime, 0, w.Bytes())
}


// EncodeNotifyCharOption builds message 1047 (NotifyCharOption).
// Schema: m_strOption(utf8) — JSON string with key bindings and smartcast config.
func EncodeNotifyCharOption(jsonPayload string) []byte {
	w := NewWriter()
	w.PutUTF8(jsonPayload)
	return BuildFrame(MsgNotifyCharOption, 0, w.Bytes())
}


// EncodeNotifySpray builds message 1569 (TankMessage.NotifySpray).
// Schema: m_sprayId(u32), m_x(i16), m_y(i16)
func EncodeNotifySpray(sprayID uint32, x, y int16) []byte {
	w := NewWriter()
	w.PutU32(sprayID)
	w.PutI16(x)
	w.PutI16(y)
	return BuildFrame(MsgNotifySpray, 0, w.Bytes())
}

// EncodeNotifySignalInfo builds message 1594 (TankMessage.NotifySignalInfo).
// Schema: m_objectId(u32), m_iDestX(i16), m_iDestY(i16), m_iSignalType(u8)
func EncodeNotifySignalInfo(objectID uint32, destX, destY int16, signalType uint8) []byte {
	w := NewWriter()
	w.PutU32(objectID)
	w.PutI16(destX)
	w.PutI16(destY)
	w.PutU8(signalType)
	return BuildFrame(MsgNotifySignalInfo, 0, w.Bytes())
}

// SceneStatEntry holds per-player battle stats for msg 1561.
type SceneStatEntry struct {
	AcctID      uint32
	Deaths      int32
	Kills       int32
	TotalKills  int32 // includes NPC kills
	Assists     int32
	DamageOut   int32
	DamageIn    int32
	BattleLevel uint8
}

// EncodeNotifySceneStat builds message 1561 (SceneMessage.NotifySceneStat).
// Schema: m_statVec(array[u16] of TankStatInfo)
// TankStatInfo: m_acctOid(u32), m_iStatData(array[u16] of i32), m_battlelevel(u8)
// Python sends 21 i32s per player: [deaths, kills, totalKills, assists, 0, 0, dmgOut, 0, 0, 0, 0, 0, 0, dmgIn, ...]
func EncodeNotifySceneStat(entries []SceneStatEntry) []byte {
	w := NewWriter()
	w.PutU16(uint16(len(entries)))
	for _, e := range entries {
		w.PutU32(e.AcctID)
		// m_iStatData: 21 i32s matching Python pk_rules.py layout
		w.PutU16(21)
		stats := [21]int32{}
		stats[0] = e.Deaths
		stats[1] = e.Kills
		stats[2] = e.TotalKills
		stats[3] = e.Assists
		stats[6] = e.DamageOut
		stats[13] = e.DamageIn
		for _, v := range stats {
			w.PutI32(v)
		}
		w.PutU8(e.BattleLevel)
	}
	return BuildFrame(MsgNotifySceneStat, 0, w.Bytes())
}
