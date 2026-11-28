package handler

import (
	"fmt"
	"log"
	"sync"
	"time"

	"bangbang-server/game"
	"bangbang-server/protocol"

	"github.com/gorilla/websocket"
)

// WSConn wraps a WebSocket connection with the protocol frame parser.
type WSConn struct {
	conn        *websocket.Conn
	mu          sync.Mutex
	store       *game.Store
	roomMgr     *game.RoomManager
	onlineMgr   *game.OnlineTracker
	broadcast   *game.Broadcaster
	questMgr    *game.QuestManager
	signMgr     *game.SignInManager
	talentMgr   *game.TalentManager
	crystalMgr  *game.CrystalManager
	mailMgr     *game.MailManager
	pveMgr      *game.PveManager
	itemCatalog *game.ItemCatalog
	session     *game.Session
	role        string // "login" or "gate"
	closed      bool
	roomID      uint32 // current room this connection is in (0 = none)
}

func NewWSConn(conn *websocket.Conn, store *game.Store, roomMgr *game.RoomManager, onlineMgr *game.OnlineTracker, broadcast *game.Broadcaster, role string, questMgr *game.QuestManager, signMgr *game.SignInManager, talentMgr *game.TalentManager, crystalMgr *game.CrystalManager, mailMgr *game.MailManager, pveMgr *game.PveManager, itemCatalog *game.ItemCatalog) *WSConn {
	return &WSConn{
		conn:        conn,
		store:       store,
		roomMgr:     roomMgr,
		onlineMgr:   onlineMgr,
		broadcast:   broadcast,
		questMgr:    questMgr,
		signMgr:     signMgr,
		talentMgr:   talentMgr,
		crystalMgr:  crystalMgr,
		mailMgr:     mailMgr,
		pveMgr:      pveMgr,
		itemCatalog: itemCatalog,
		role:        role,
	}
}

// Send writes a raw binary frame to the WebSocket.
func (c *WSConn) Send(frame []byte) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return fmt.Errorf("connection closed")
	}
	c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	return c.conn.WriteMessage(websocket.BinaryMessage, frame)
}

// SendMulti writes multiple frames.
func (c *WSConn) SendMulti(frames ...[]byte) error {
	for _, f := range frames {
		if f == nil {
			continue
		}
		if err := c.Send(f); err != nil {
			return err
		}
	}
	return nil
}

// Close closes the connection.
func (c *WSConn) Close() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.closed {
		c.closed = true
		c.conn.Close()
	}
}

// HandleLoop reads and dispatches messages from the client.
func (c *WSConn) HandleLoop() {
	defer c.Close()
	defer func() {
		// Cleanup on disconnect: remove from online tracker and room
		if c.session != nil && c.session.Character != nil {
			charID := c.session.Character.CharID
			c.broadcast.Unregister(charID, c)
			if !c.broadcast.Has(charID) {
				c.onlineMgr.Remove(charID)
			}
			// Notify room members if in a room
			if c.roomID != 0 {
				room := c.roomMgr.GetRoom(c.roomID)
				_, newOwner := c.roomMgr.RemoveMemberWithTransfer(charID)
				if room != nil {
					remaining := c.roomMgr.GetMembers(room.ID)
					// Broadcast leave (RoomOp 1 = leave) to remaining members
					leaveFrame := protocol.EncodeNotifyRoomOp(1, charID, charID)
					c.broadcast.SendToAll(remaining, charID, leaveFrame)
					if newOwner != 0 {
						ownerFrame := protocol.EncodeNotifyRoomOp(26, newOwner, newOwner)
						c.broadcast.SendToAll(remaining, 0, ownerFrame)
						log.Printf("[%s] transferred room %d ownership to %d", c.role, room.ID, newOwner)
					}
				}
			}
			log.Printf("[%s] player %s (id=%d) went offline", c.role, c.session.Character.Name, charID)
		}
	}()

	// Step 1: Send greeting (0x0000)
	if err := c.Send(protocol.Greeting()); err != nil {
		log.Printf("[%s] greeting send error: %v", c.role, err)
		return
	}

	parser := protocol.NewFrameParser()

	for {
		c.conn.SetReadDeadline(time.Now().Add(120 * time.Second))
		msgType, data, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
				log.Printf("[%s] client disconnected normally (%v)", c.role, err)
			} else {
				log.Printf("[%s] read error: %v", c.role, err)
			}
			return
		}
		if msgType != websocket.BinaryMessage {
			log.Printf("[%s] non-binary message, ignoring", c.role)
			continue
		}

		frames, err := parser.Feed(data)
		if err != nil {
			log.Printf("[%s] frame parse error: %v", c.role, err)
			return
		}

		for _, frame := range frames {
			if err := c.handleFrame(frame); err != nil {
				log.Printf("[%s] handle error: %v", c.role, err)
				return
			}
		}
	}
}

func (c *WSConn) handleFrame(frame []byte) error {
	msgID, _, body, err := protocol.ParseFrameHeader(frame)
	if err != nil {
		return err
	}

	log.Printf("[%s] ← msg %d, body %d bytes", c.role, msgID, len(body))

	switch msgID {

	case protocol.MsgRequestProtocolVersion:
		return c.handleVersion(body)

	case protocol.MsgRequestAuthLogin:
		return c.handleAuthLogin(body)

	case protocol.MsgRequestServerLogin:
		return c.handleServerLogin(body)

	case protocol.MsgWorldEnterMessage:
		return c.handleWorldEnter(body)

	case protocol.MsgRequestContainerItem: // 165
		req, err := protocol.DecodeRequestContainerItem(body)
		if err != nil {
			return err
		}
		log.Printf("[gate] request container items: cont=%d", req.ContType)
		if req.ContType == 0 {
			for _, ct := range []uint32{2, 3, 4, 6, 7} {
				frame := c.encodeItemList(ct, 1)
				if frame != nil {
					c.Send(frame)
				}
			}
			return nil
		}
		frame := c.encodeItemList(req.ContType, 1)
		if frame != nil {
			return c.Send(frame)
		}
		return nil

	case protocol.MsgRequestLevelUpTank: // 203
		uuid, err := protocol.DecodeTankUUIDOnly(body)
		if err != nil {
			return err
		}
		log.Printf("[gate] level up tank: uuid=%s", uuid)
		if c.session == nil {
			return nil
		}
		tank, err := c.store.LevelUpTank(c.session.CharID, uuid)
		if err != nil {
			log.Printf("[gate] level up tank error: %v", err)
			return nil
		}
		log.Printf("[gate] tank %s level up success: level=%d", uuid, tank.TankLevel)
		return c.Send(c.encodeTankList(1, 0))

	case protocol.MsgRequestStrengthenTank: // 204
		uuid, err := protocol.DecodeTankUUIDOnly(body)
		if err != nil {
			return err
		}
		log.Printf("[gate] strengthen tank: uuid=%s", uuid)
		if c.session == nil {
			return nil
		}
		tank, err := c.store.StrengthenTank(c.session.CharID, uuid)
		if err != nil {
			log.Printf("[gate] strengthen tank error: %v", err)
			return nil
		}
		log.Printf("[gate] tank %s strengthen success: stthLevel=%d", uuid, tank.StthLevel)
		return c.Send(c.encodeTankList(1, 0))

	case protocol.MsgRequestChangeBattleTank: // 200
		tankUUID, err := protocol.DecodeTankUUIDOnly(body)
		if err != nil {
			log.Printf("[gate] decode ChangeBattleTank error: %v", err)
			return nil
		}
		log.Printf("[gate] change battle tank: uuid=%s", tankUUID)
		if c.session == nil {
			return nil
		}
		oldTank, newTank, err := c.store.ChangeBattleTank(c.session.CharID, tankUUID)
		if err != nil {
			log.Printf("[gate] change battle tank error: %v", err)
			return nil
		}
		var frames [][]byte
		if oldTank != nil {
			frames = append(frames, protocol.EncodeUpdateTankInstance(toProtocolTank(oldTank), 8))
		}
		if newTank != nil {
			frames = append(frames, protocol.EncodeUpdateTankInstance(toProtocolTank(newTank), 8))
			// If in room, broadcast NotifyTankSelected (1727) to room members
			room := c.roomMgr.GetRoom(c.roomID)
			if room == nil && c.session != nil && c.session.Character != nil {
				room = c.roomMgr.FindRoomByMember(c.session.Character.CharID)
				if room != nil {
					c.roomID = room.ID
				}
			}
			if room != nil {
				tankFrame := protocol.EncodeNotifyTankSelected(c.session.CharID, newTank.TankID, 1, newTank.ExternalID, 0, 0)
				c.broadcast.SendToAll(room.Members, 0, tankFrame)
				camp := c.roomMgr.GetMemberCamp(room.ID, c.session.CharID)
				c.roomMgr.SetMemberBrief(room.ID, c.session.CharID, c.buildCharBrief(camp))
			}
		}
		return c.SendMulti(frames...)

	case protocol.MsgRequestBuyGoods: // 250
		req, err := protocol.DecodeBuyGoodsMessage(body)
		if err != nil {
			log.Printf("[gate] decode BuyGoods error: %v", err)
			return c.Send(protocol.EncodeRejectGoodsBuy())
		}
		log.Printf("[gate] buy goods: id=%d count=%d coin=%d price=%d", req.GoodsID, req.Count, req.CoinType, req.Price)
		if c.session == nil {
			return c.Send(protocol.EncodeRejectGoodsBuy())
		}
		var offerInfo *game.ShopOfferInfo
		catalogOffer := GetShopOffer(req.GoodsID)
		if catalogOffer != nil {
			offerInfo = &game.ShopOfferInfo{
				IsTank:        catalogOffer.Tab == 2 || catalogOffer.GrantKind == "tank",
				ItemID:        uint32(catalogOffer.ItemID),
				ContainerType: uint8(catalogOffer.ContainerType),
			}
		}
		char, addedTank, addedItem, err := c.store.BuyGoods(c.session.CharID, req.GoodsID, req.CoinType, req.Price, req.Count, offerInfo)
		if err != nil {
			log.Printf("[gate] buy goods %d failed: %v", req.GoodsID, err)
			return c.Send(protocol.EncodeRejectGoodsBuy())
		}
		okFrame := protocol.EncodeNotifyBuyGoodsOk(req.BuyType, req.GoodsID)
		curFrame := protocol.EncodeNotifyCharCurrency(&protocol.CharCurrency{
			Cash:   char.Cash,
			Golden: char.Golden,
			Silver: char.Silver,
		})
		var frames [][]byte
		frames = append(frames, okFrame, curFrame)
		if addedTank != nil {
			frames = append(frames, protocol.EncodeUpdateTankInstance(toProtocolTank(addedTank), 1))
			frames = append(frames, c.encodeTankList(1, 0))
		}
		if addedItem != nil {
			frames = append(frames, protocol.EncodeUpdateItemInstance(uint32(addedItem.ContType), toProtocolItem(addedItem)))
			frames = append(frames, c.encodeItemList(uint32(addedItem.ContType), 1))
		}
		return c.SendMulti(frames...)

	case protocol.MsgRequestCleanUpCont: // 152
		req, err := protocol.DecodeRequestCleanUpCont(body)
		if err != nil {
			return err
		}
		log.Printf("[gate] clean up / sort bag: cont=%d", req.ContType)
		if c.session == nil {
			return nil
		}
		c.store.CleanUpCont(c.session.CharID, uint8(req.ContType))
		return c.Send(c.encodeItemList(req.ContType, 1))

	case protocol.MsgRequestUseItem: // 153
		req, err := protocol.DecodeRequestUseItem(body)
		if err != nil {
			return err
		}
		log.Printf("[gate] use item: cont=%d slot=%d count=%d target=%s", req.ContType, req.SlotNo, req.Count, req.TargetUuid)
		if c.session == nil {
			return nil
		}
		charID := c.session.CharID

		// Special: container 4 (avatar) or 7 (background) → cosmetic equip
		if req.ContType == 4 || req.ContType == 7 {
			if req.ContType == 7 && req.SlotNo == -1 {
				// Unequip background → set decorateId=0
				c.store.SetDecorate(charID, 0)
			} else {
				item := c.store.FindItemBySlot(charID, uint8(req.ContType), req.SlotNo)
				if item != nil {
					if req.ContType == 4 {
						c.store.SetAvatar(charID, item.TemplateID)
					} else {
						c.store.SetDecorate(charID, item.TemplateID)
					}
					// Set CUR_USE ext_flag on selected, clear on others
					c.store.SetExtFlagCurUse(charID, uint8(req.ContType), req.SlotNo)
				}
			}
			bagFrame := c.encodeItemList(req.ContType, 1)
			return c.Send(bagFrame)
		}

		// Look up the item template before consuming
		item := c.store.FindItemBySlot(charID, uint8(req.ContType), req.SlotNo)
		if item == nil {
			return c.Send(protocol.EncodeNotifyItemFailed(req.ContType, req.SlotNo))
		}
		templateID := item.TemplateID

		// --- Gift Box / Egg (type 20/27 from normal_shop_catalog.json) ---
		if c.itemCatalog != nil && c.itemCatalog.IsBox(templateID) {
			if err := c.itemCatalog.ValidateCanOpenBox(c.store, charID, templateID); err != nil {
				log.Printf("[gate] open box blocked: %v", err)
				return c.Send(protocol.EncodeNotifyItemFailed(req.ContType, req.SlotNo))
			}
			rewards, err := c.itemCatalog.OpenBox(templateID)
			if err != nil {
				log.Printf("[gate] open box error: %v", err)
				return c.Send(protocol.EncodeNotifyItemFailed(req.ContType, req.SlotNo))
			}
			removedUUID, remaining := c.store.RemoveItem(charID, uint8(req.ContType), req.SlotNo, 1)
			frames := c.grantRewardsFrames(charID, rewards, req.ContType, req.SlotNo, removedUUID, remaining, true)
			return c.SendMulti(frames...)
		}

		// --- Present / Gift Package (from bag.json "presents") ---
		if c.itemCatalog != nil && c.itemCatalog.IsPresent(templateID) {
			count := req.Count
			if count <= 0 {
				count = 1
			}
			if count > item.Count {
				count = item.Count
			}
			rewards, err := c.itemCatalog.OpenPresent(templateID, count)
			if err != nil {
				log.Printf("[gate] open present error: %v", err)
				return c.Send(protocol.EncodeNotifyItemFailed(req.ContType, req.SlotNo))
			}
			removedUUID, remaining := c.store.RemoveItem(charID, uint8(req.ContType), req.SlotNo, count)
			frames := c.grantRewardsFrames(charID, rewards, req.ContType, req.SlotNo, removedUUID, remaining, true)
			return c.SendMulti(frames...)
		}

		// --- Tank Card (type 46 from bag.json) ---
		if c.itemCatalog != nil {
			if tankID, ok := c.itemCatalog.GetTankCardReward(templateID); ok {
				removedUUID, remaining := c.store.RemoveItem(charID, uint8(req.ContType), req.SlotNo, 1)
				rewards := []game.GrantedReward{{Kind: "tank", ID: tankID, Quantity: 1}}
				frames := c.grantRewardsFrames(charID, rewards, req.ContType, req.SlotNo, removedUUID, remaining, true)
				return c.SendMulti(frames...)
			}
		}

		// --- Fallback: item has no configured reward in catalog/presents ---
		log.Printf("[gate] use item: no reward config for template=%d", templateID)
		return c.Send(protocol.EncodeNotifyItemFailed(req.ContType, req.SlotNo))

	case protocol.MsgRequestChangeSetting: // 79 — setting flags
		if len(body) >= 4 {
			r := protocol.NewReader(body)
			flags, _ := r.GetU32()
			log.Printf("[%s] setting flags = %d", c.role, flags)
			if c.session != nil {
				c.store.SetSettingFlag(c.session.CharID, flags)
			}
			return c.Send(protocol.EncodeNotifySettingFlag(flags))
		}
		return nil

	case protocol.MsgRequestSetCharOption: // 88 — key binding / smartcast
		if len(body) >= 2 {
			r := protocol.NewReader(body)
			jsonStr, _ := r.GetUTF8()
			log.Printf("[%s] char option: %s", c.role, jsonStr)
			if c.session != nil {
				c.store.SetCharOption(c.session.CharID, jsonStr)
			}
			// Echo back as 1047 to confirm
			return c.Send(protocol.EncodeNotifyCharOption(jsonStr))
		}
		return nil

	case protocol.MsgSystemHeartBeat:
		return c.Send(protocol.EncodeHeartBeat())

	case protocol.MsgRequestPing:
		now := uint32(time.Now().UnixMilli() & 0xFFFFFFFF)
		var clientMs uint32
		if len(body) >= 4 {
			r := protocol.NewReader(body)
			clientMs, _ = r.GetU32()
		}
		return c.Send(protocol.EncodePingResponse(clientMs, now))

	case protocol.MsgRequestFriendApplyList:
		return c.SendMulti(
			protocol.EncodeNotifyFriendApplyList(),
			protocol.EncodeNotifyFriendApplyCount(0),
		)

	case protocol.MsgRequestSoloPveInfo:
		return c.Send(protocol.EncodeNotifyCityInfoInit())

	case protocol.MsgOpenBossActUI:
		return c.SendMulti(
			protocol.EncodeNotifyBossState(1, 2),
			protocol.EncodeNotifyBossSnapshot(1, 10000000, 10000000, 0, 0),
		)

	case protocol.MsgCloseBossActUI:
		return nil

	case protocol.MsgRequestPlayerList:
		var listType uint8
		if len(body) > 0 {
			listType = body[0]
		}
		// Build player brief list from online tracker
		onlinePlayers := c.onlineMgr.List()
		briefs := make([]protocol.PlayerBriefData, 0, len(onlinePlayers))
		for _, op := range onlinePlayers {
			briefs = append(briefs, protocol.PlayerBriefData{
				AcctID:   op.CharID,
				CharUUID: op.CharUUID,
				Name:     op.Name,
				Level:    op.Level,
				AvatarID: op.AvatarID,
			})
		}
		return c.Send(protocol.EncodeNotifyPlayerList(listType, briefs))

	case protocol.MsgRequestInHall:
		var roomType uint8 = 1
		var site int32 = 0
		if len(body) >= 1 {
			roomType = body[0]
		}
		if len(body) >= 5 {
			site = int32(body[1]) | int32(body[2])<<8 | int32(body[3])<<16 | int32(body[4])<<24
		}
		// Build room list from room manager (show all rooms regardless of type filter)
		rooms := c.roomMgr.ListRooms(0)
		log.Printf("[%s] hall request: roomType=%d, found %d rooms", c.role, roomType, len(rooms))
		roomData := make([]protocol.RoomInfoData, 0, len(rooms))
		for _, r := range rooms {
			roomData = append(roomData, protocol.RoomInfoData{
				RoomID:     r.ID,
				NumPlayers: uint32(len(r.Members)),
				MaxPlayers: r.MaxSlots,
				MapID:      r.MapID,
				Mode:       r.Mode,
				State:      r.State,
				IsValidate: 0,
				RoomType:   r.Type,
				Name:       r.Name,
				TeamID:     0,
			})
		}
		return c.Send(protocol.EncodeNotifyHallDisplayList(site, roomType, roomData))

	case protocol.MsgRequestOutHall:
		return nil

	case protocol.MsgRequestStartMatch:
		var roomType uint8 = 1
		if len(body) > 0 {
			roomType = body[0]
		}
		log.Printf("[%s] match requested: roomType=%d", c.role, roomType)
		// Send NotifyStartMatch (1719) so the client shows the pairing timer.
		// pairTime=0 (just started), matchType=roomType, avgTime=10s, count=1
		return c.Send(protocol.EncodeNotifyStartMatch(0, roomType, 10, 1))

	case protocol.MsgRequestStopMatch:
		log.Printf("[%s] match stop requested", c.role)
		return c.Send(protocol.EncodeNotifyStopMatch())

	case protocol.MsgRequestSetMap:
		if len(body) < 4 {
			return nil
		}
		r := protocol.NewReader(body)
		mapID, _ := r.GetU32()
		if mapID == 0 {
			mapID = game.RandomMapID()
			log.Printf("[%s] random map selected: mapID=%d", c.role, mapID)
		} else {
			log.Printf("[%s] set map: mapID=%d", c.role, mapID)
		}
		mapFrame := protocol.EncodeNotifyRoomMap(mapID)
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil && c.session != nil && c.session.Character != nil {
			room = c.roomMgr.FindRoomByMember(c.session.Character.CharID)
			if room != nil {
				c.roomID = room.ID
			}
		}
		if room != nil {
			c.roomMgr.UpdateMap(room.ID, mapID)
			c.broadcast.SendToAll(room.Members, 0, mapFrame)
			return nil
		}
		return c.Send(mapFrame)

	case protocol.MsgRequestCreateRoom:
		req, err := protocol.DecodeRequestCreateRoom(body)
		if err != nil {
			log.Printf("[%s] decode create room err: %v", c.role, err)
			return nil
		}
		if c.session == nil || c.session.Character == nil {
			return nil
		}
		p := c.session.Character
		creatorBrief := c.buildCharBrief(1) // host is Camp 1 (Camp A)
		mapID := req.MapID
		if mapID == 0 {
			mapID = game.RandomMapID()
			log.Printf("[%s] random map for new room: mapID=%d", c.role, mapID)
		}
		// Create room in room manager (keep original room type as-is)
		room := c.roomMgr.CreateRoom(req.Name, req.BType, uint32(req.BMode), mapID, req.Password, p.CharID, creatorBrief)
		c.roomID = room.ID
		frame := protocol.EncodeEnterRoomOk(room.ID, p.CharID, req.Name, req.BType, uint32(req.BMode), mapID, req.Password, creatorBrief)
		log.Printf("[%s] room created: id=%d, name=%s, type=%d, map=%d", c.role, room.ID, req.Name, req.BType, mapID)
		return c.Send(frame)

	case protocol.MsgRequestJoinRoom:
		if len(body) < 4 {
			return nil
		}
		r := protocol.NewReader(body)
		roomID, _ := r.GetU32()
		log.Printf("[%s] join room requested: roomID=%d", c.role, roomID)
		room := c.roomMgr.GetRoom(roomID)
		if room == nil {
			log.Printf("[%s] room %d not found", c.role, roomID)
			return nil
		}
		if c.session == nil || c.session.Character == nil {
			return nil
		}
		p := c.session.Character

		guestCamp := uint8(2) // guest is Camp 2 (Camp B)
		joinBrief := c.buildCharBrief(guestCamp)

		// Get existing members' briefs BEFORE adding the new member
		existingBriefs := c.roomMgr.GetMemberBriefs(roomID)
		existingMembers := make([]uint32, len(room.Members))
		copy(existingMembers, room.Members)

		// Add to room with assigned camp
		c.roomMgr.AddMember(roomID, p.CharID, joinBrief, guestCamp)
		c.roomID = roomID

		// Send EnterRoomOk to joiner with ALL members (existing + self)
		allBriefs := append(existingBriefs, joinBrief)
		joinFrame := protocol.EncodeEnterRoomOk(roomID, room.OwnerID, room.Name, room.Type, room.Mode, room.MapID, room.Password, allBriefs...)
		log.Printf("[%s] player %s joined room %d (%d members now, camp=%d)", c.role, p.Name, roomID, len(allBriefs), guestCamp)
		if err := c.Send(joinFrame); err != nil {
			return err
		}

		// Broadcast NotifyRoomAdd to existing members
		addFrame := protocol.EncodeNotifyRoomAdd(joinBrief, 0)
		c.broadcast.SendToAll(existingMembers, p.CharID, addFrame)
		return nil

	case protocol.MsgRequestRoomOp:
		var roomOp uint8 = 1
		var target uint32
		if len(body) >= 1 {
			roomOp = body[0]
		}
		if len(body) >= 5 {
			target = uint32(body[1]) | uint32(body[2])<<8 | uint32(body[3])<<16 | uint32(body[4])<<24
		}
		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
			if target == 0 {
				target = charID
			}
		}
		log.Printf("[%s] room op=%d start=%d target=%d (roomID=%d)", c.role, roomOp, charID, target, c.roomID)
		opFrame := protocol.EncodeNotifyRoomOp(roomOp, charID, target)
		// Broadcast to all room members
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil && charID != 0 {
			room = c.roomMgr.FindRoomByMember(charID)
			if room != nil {
				c.roomID = room.ID
			}
		}
		if room != nil {
			log.Printf("[%s] broadcasting roomOp=%d to room %d members: %v", c.role, roomOp, room.ID, room.Members)
			// Broadcast opFrame to all room members
			c.broadcast.SendToAll(room.Members, 0, opFrame)

			if roomOp == 1 {
				// Leave room
				log.Printf("[%s] player %d left room %d", c.role, charID, room.ID)
				_, newOwner := c.roomMgr.RemoveMemberWithTransfer(charID)
				c.roomID = 0
				if newOwner != 0 {
					remaining := c.roomMgr.GetMembers(room.ID)
					ownerFrame := protocol.EncodeNotifyRoomOp(26, newOwner, newOwner)
					c.broadcast.SendToAll(remaining, 0, ownerFrame)
					log.Printf("[%s] transferred room %d ownership to %d", c.role, room.ID, newOwner)
				}
			} else if roomOp == 20 {
				// Kick member
				log.Printf("[%s] host %d kicked member %d from room %d", c.role, charID, target, room.ID)
				c.roomMgr.RemoveMember(target)
			} else if roomOp == 2 || roomOp == 3 {
				// Ready (2) / Unready (3)
				ready := (roomOp == 2)
				c.roomMgr.SetMemberReady(room.ID, charID, ready)
				log.Printf("[%s] player %d ready=%v in room %d", c.role, charID, ready, room.ID)
			} else if roomOp == 4 {
				// Switch camp: update camp & stored brief for this member
				newCamp := c.roomMgr.SwitchCamp(room.ID, charID)
				log.Printf("[%s] player %d switched to camp %d in room %d", c.role, charID, newCamp, room.ID)
			}

			// If op == 24, host is starting the match -> broadcast NotifyStartGame (1705)
			if roomOp == 24 {
				// If map is 0 (random), pick one now
				if room.MapID == 0 {
					room.MapID = game.RandomMapID()
					c.roomMgr.UpdateMap(room.ID, room.MapID)
					log.Printf("[%s] 🎲 random map for start: mapID=%d", c.role, room.MapID)
					// notify all players of the chosen map
					mapFrame := protocol.EncodeNotifyRoomMap(room.MapID)
					c.broadcast.SendToAll(room.Members, 0, mapFrame)
				}
				log.Printf("[%s] 🚀 starting match for room %d (map=%d, %d players: %v)",
					c.role, room.ID, room.MapID, len(room.Members), room.Members)
				room.State = 1 // in-battle
				c.roomMgr.ResetLoaded(room.ID)
				briefs := c.roomMgr.GetMemberBriefs(room.ID)
				// Override room type 1-9 → 2 for battle start so result_mv vinh danh plays
				startRoomType := room.Type
				if startRoomType >= 1 && startRoomType <= 9 {
					startRoomType = 2
				}
				startFrame := protocol.EncodeNotifyStartGame(room.ID, room.MapID, startRoomType, briefs, 0)
				c.broadcast.SendToAll(room.Members, 0, startFrame)
			}
			return nil
		}
		log.Printf("[%s] room op=%d start=%d target=%d (not in room, sending to self)", c.role, roomOp, charID, target)
		return c.Send(opFrame)

	case protocol.MsgSyncLoadAndDelay:
		if len(body) < 16 {
			return nil
		}
		r := protocol.NewReader(body)
		sceneID, _ := r.GetU32()
		tankID, _ := r.GetU32()
		delay, _ := r.GetU32()
		loaded, _ := r.GetU32()
		log.Printf("[%s] load progress: scene=%d tank=%d delay=%d loaded=%d%%", c.role, sceneID, tankID, delay, loaded)

		rateFrame := protocol.EncodeNotifyLoadedRate(tankID, delay, loaded)
		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
		}
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil && charID != 0 {
			room = c.roomMgr.FindRoomByMember(charID)
			if room != nil {
				c.roomID = room.ID
			}
		}
		if room == nil && tankID != 0 {
			room = c.roomMgr.FindRoomByMember(tankID)
			if room != nil {
				c.roomID = room.ID
			}
		}
		if room != nil {
			c.broadcast.SendToAll(room.Members, 0, rateFrame)
			if loaded >= 100 {
				c.roomMgr.MarkLoaded(room.ID, tankID)
				if c.roomMgr.AllLoaded(room.ID) && c.roomMgr.SetBattleStarted(room.ID) {
					log.Printf("[%s] 🎯 all players loaded for room %d! Starting battle...", c.role, room.ID)
					c.startBattle(room)
				}
			}
			return nil
		}
		return c.Send(rateFrame)

	case protocol.MsgRequestMoveForward:
		req, err := protocol.DecodeRequestMoveForward(body)
		if err != nil {
			log.Printf("[%s] decode move err: %v", c.role, err)
			return nil
		}
		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
		}
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil && charID != 0 {
			room = c.roomMgr.FindRoomByMember(charID)
			if room != nil {
				c.roomID = room.ID
			}
		}
		if room != nil && charID != 0 {
			// Block movement if dead, stunned, or battle finished
			if room.Battle != nil && (!room.Battle.IsAlive(charID) || room.Battle.IsFinished() || room.Battle.IsStunned(charID, time.Now().UnixMilli())) {
				return nil
			}
			// Server-side movement validation: reject position inside movement walls (solid + water)
			// Python reference: battle_map.py uses movement_walls (solid + water + NPC rects) for vehicle blocking
			if room.Battle != nil {
				destX, destY := float64(req.StartX), float64(req.StartY)
				if game.PointInsideWall(room.Battle.MoveWalls, destX, destY) {
					return nil // position inside water or solid wall — reject
				}
				if game.PointInsideWall(game.NPCMovementWalls(room.Battle.NPCs), destX, destY) {
					return nil // position inside alive NPC bounding box — reject
				}
			}
			tankID := c.roomMgr.GetMemberTank(room.ID, charID)
			moveSpeed := game.GetTankConfig(tankID).MoveSpeed
			c.roomMgr.SetMemberPos(room.ID, charID, int16(req.StartX), int16(req.StartY))
			syncFrame := protocol.EncodeSyncSceneMove(charID, int16(req.StartX), int16(req.StartY), moveSpeed, req.Direction, 0)
			c.broadcast.SendToAll(room.Members, charID, syncFrame)
		}
		return nil

	case protocol.MsgRequestUseSkill:
		req, err := protocol.DecodeRequestUseSkill(body)
		if err != nil {
			log.Printf("[%s] decode skill err: %v", c.role, err)
			return nil
		}
		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
		}
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil && charID != 0 {
			room = c.roomMgr.FindRoomByMember(charID)
			if room != nil {
				c.roomID = room.ID
			}
		}
		if room != nil && charID != 0 {
			// Check if player is alive, not CC'd, battle is not finished, and slot is off cooldown
			nowMS := time.Now().UnixMilli()
			if room.Battle != nil && (!room.Battle.IsAlive(charID) || room.Battle.IsFinished() || !room.Battle.CanCastSlot(charID, req.SlotNo, nowMS) || room.Battle.IsSlotOnCooldown(charID, req.SlotNo, nowMS)) {
				return nil
			}
			startX, startY := c.roomMgr.GetMemberPos(room.ID, charID)
			tankID := c.roomMgr.GetMemberTank(room.ID, charID)
			cfg := game.GetTankConfig(tankID)
			var mpCost int32
			if cfg != nil {
				switch req.SlotNo {
				case 1:
					mpCost = cfg.Skills[0].MPCost
				case 2:
					mpCost = cfg.Skills[1].MPCost
				case 3, 10:
					mpCost = cfg.Skills[3].MPCost
				}
			}
			if mpCost > 0 && room.Battle != nil && !room.Battle.HasEnoughMP(charID, mpCost) {
				return nil
			}
			beh := c.roomMgr.GetMemberBehavior(room.ID, charID, tankID)
			var walls []game.WallRect
			var bounds game.ArenaBounds
			if room.Battle != nil {
				walls = room.Battle.MoveWalls
				bounds = room.Battle.MapBounds
			}
			ctx := &game.ActorContext{
				RoomID:  room.ID,
				ActorID: charID,
				TankID:  tankID,
				Camp:    c.roomMgr.GetMemberCamp(room.ID, charID),
				PosX:    startX,
				PosY:    startY,
				Config:  cfg,
				Walls:   walls,
				Bounds:  bounds,
			}
			if room.Battle != nil {
				room.Battle.BehaviorMu.Lock()
			}
			res := beh.OnUseSkill(ctx, req.SlotNo, req.TargetID, req.DestX, req.DestY)
			if room.Battle != nil {
				room.Battle.BehaviorMu.Unlock()
			}
			if mpCost > 0 && room.Battle != nil && (len(res.Fires) > 0 || len(res.Skills) > 0 || len(res.AreaHits) > 0 || len(res.Moves) > 0 || len(res.Buffs) > 0) {
				if newMP, ok := room.Battle.ConsumeMP(charID, mpCost); ok {
					c.broadcast.SendToAll(room.Members, 0, protocol.EncodeSyncSceneMP([]struct {
						ObjID uint32
						MP    int32
					}{{charID, newMP}}))
				}
			}
			c.dispatchActionResult(room, charID, tankID, req.SlotNo, res)
		}
		return nil

	case protocol.MsgRequestSurrenderVotation:
		// C→S: request to start a surrender vote. Body: u32 sceneId.
		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
		}
		if charID == 0 {
			return nil
		}
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil {
			room = c.roomMgr.FindRoomByMember(charID)
		}
		if room == nil || room.Battle == nil || room.Battle.IsFinished() {
			return nil
		}
		bs := room.Battle
		sponsorCamp := c.roomMgr.GetMemberCamp(room.ID, charID)
		if sponsorCamp == 0 {
			return nil
		}

		// Collect team members (same camp as sponsor)
		allMembers := c.roomMgr.GetMembers(room.ID)
		var teamIDs []uint32
		for _, mid := range allMembers {
			mc := c.roomMgr.GetMemberCamp(room.ID, mid)
			if mc == sponsorCamp {
				teamIDs = append(teamIDs, mid)
			}
		}
		if len(teamIDs) < 1 {
			return nil
		}

		nowMS := time.Now().UnixMilli()
		result := bs.StartSurrenderVote(charID, teamIDs, nowMS)

		if result.OnCooldown || result.AlreadyActive {
			return nil
		}
		if !result.Started {
			return nil
		}

		// Send 1597 to team members
		showEnd := bs.GetBattleSeconds(bs.VoteEndAt)
		nextTime := bs.GetBattleSeconds(nowMS + game.VoteCooldownMS) // next allowed vote time
		frame := protocol.EncodeNotifyShowSurrenderVotation(result.ValidCount, showEnd, nextTime, charID)
		c.broadcast.SendToAll(teamIDs, 0, frame)

		// If only 1 player on team, auto-pass
		if len(teamIDs) == 1 {
			winner := uint8(3 - sponsorCamp)
			bs.ForceEndSurrender(winner)
			log.Printf("[battle] 🏳️ solo surrender by %d, camp%d wins", charID, winner)
		}

		log.Printf("[battle] 🗳️ surrender vote started by %d (camp%d), %d voters", charID, sponsorCamp, len(teamIDs))
		return nil

	case protocol.MsgVoteSurrender:
		// C→S: cast a surrender vote. Body: u8 vote + u32 sceneId.
		if len(body) < 5 {
			return nil
		}
		voteValue := body[0] // 2=agree, 1=deny
		agree := voteValue == 2

		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
		}
		if charID == 0 {
			return nil
		}
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil {
			room = c.roomMgr.FindRoomByMember(charID)
		}
		if room == nil || room.Battle == nil || room.Battle.IsFinished() {
			return nil
		}
		bs := room.Battle
		nowMS := time.Now().UnixMilli()
		result := bs.CastSurrenderVote(charID, agree, nowMS)

		if result.ValidCount == 0 {
			return nil
		}

		// Broadcast 1598 update to team
		updateFrame := protocol.EncodeUpdateVotationInfo(result.ValidCount, result.VoteSlice)
		c.broadcast.SendToAll(result.TeamIDs, 0, updateFrame)

		if result.Passed {
			// Surrender passed — opposing camp wins
			sponsorCamp := c.roomMgr.GetMemberCamp(room.ID, result.Sponsor)
			winner := uint8(3 - sponsorCamp)
			bs.ForceEndSurrender(winner)
			log.Printf("[battle] 🏳️ surrender vote passed! camp%d surrenders, camp%d wins", sponsorCamp, winner)
		} else if result.Failed {
			// Vote failed — send cooldown to team
			coolSec := bs.GetVoteCooldownSeconds(nowMS)
			coolFrame := protocol.EncodeNotifySurrenderVotationCoolTime(coolSec)
			c.broadcast.SendToAll(result.TeamIDs, 0, coolFrame)
			log.Printf("[battle] 🗳️ surrender vote failed, cooldown until %ds", coolSec)
		}
		return nil

	case protocol.MsgRequestOpSpray: // 507 — spray paint
		if len(body) < 8 {
			return nil
		}
		r := protocol.NewReader(body)
		_, _ = r.GetU32() // sceneId
		x, _ := r.GetI16()
		y, _ := r.GetI16()
		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
		}
		if charID == 0 {
			return nil
		}
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil {
			room = c.roomMgr.FindRoomByMember(charID)
		}
		if room == nil {
			return nil
		}
		// Use the player's equipped spray ID (from CharBasic.SprayID)
		sprayID := uint32(0)
		if c.session.Character.AvatarID > 0 {
			// Default spray 1 for now — TODO: store equipped spray per character
			sprayID = 1
		}
		sprayFrame := protocol.EncodeNotifySpray(sprayID, x, y)
		c.broadcast.SendToAll(room.Members, 0, sprayFrame)
		log.Printf("[%s] spray from %d at (%d,%d) sprayID=%d", c.role, charID, x, y, sprayID)
		return nil

	case protocol.MsgRequestSignalInfo: // 511 — minimap signal (attack/retreat/rally)
		if len(body) < 9 {
			return nil
		}
		r := protocol.NewReader(body)
		_, _ = r.GetU32() // sceneId
		destX, _ := r.GetI16()
		destY, _ := r.GetI16()
		sigType, _ := r.GetU8()
		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
		}
		if charID == 0 {
			return nil
		}
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil {
			room = c.roomMgr.FindRoomByMember(charID)
		}
		if room == nil {
			return nil
		}
		// Broadcast signal to same-camp team members
		camp := c.roomMgr.GetMemberCamp(room.ID, charID)
		var teamIDs []uint32
		for _, mid := range room.Members {
			if c.roomMgr.GetMemberCamp(room.ID, mid) == camp {
				teamIDs = append(teamIDs, mid)
			}
		}
		sigFrame := protocol.EncodeNotifySignalInfo(charID, destX, destY, sigType)
		c.broadcast.SendToAll(teamIDs, 0, sigFrame)
		log.Printf("[%s] signal type=%d from %d at (%d,%d) to %d teammates", c.role, sigType, charID, destX, destY, len(teamIDs))
		return nil

	case protocol.MsgRequestExitBattleEnd:
		var exitType uint8 = 2 // 2=return to room, 3=exit to lobby/hall
		if len(body) >= 1 {
			exitType = body[0]
		}
		log.Printf("[%s] exit battle end requested (m_type=%d)", c.role, exitType)
		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
		}
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil && charID != 0 {
			room = c.roomMgr.FindRoomByMember(charID)
		}
		exitFrame := protocol.EncodeNotifyExitBattle(0, 0, charID, uint32(exitType), 0)
		if room != nil {
			// If battle is still running, handle mid-battle leave
			if room.Battle != nil && !room.Battle.IsFinished() {
				// Mark this player as dead (forfeit)
				if s := room.Battle.GetMemberState(charID); s != nil {
					s.Alive = false
					s.RespawnAt = 0 // no respawn for quitters
				}
				// Check if entire team has left → other team wins
				leaverCamp := c.roomMgr.GetMemberCamp(room.ID, charID)
				_, newOwner := c.roomMgr.RemoveMemberWithTransfer(charID)
				c.roomID = 0

				// Check remaining members per camp
				remainingMembers := c.roomMgr.GetMembers(room.ID)
				campAlive := [3]bool{}
				for _, mid := range remainingMembers {
					mc := c.roomMgr.GetMemberCamp(room.ID, mid)
					campAlive[mc] = true
				}
				opFrame := protocol.EncodeNotifyRoomOp(1, charID, 0)
				c.broadcast.SendToAll(remainingMembers, 0, opFrame)
				if newOwner != 0 {
					ownerFrame := protocol.EncodeNotifyRoomOp(26, newOwner, newOwner)
					c.broadcast.SendToAll(remainingMembers, 0, ownerFrame)
					log.Printf("[%s] transferred room %d ownership to %d", c.role, room.ID, newOwner)
				}

				if !campAlive[leaverCamp] {
					// All members of leaverCamp gone → other team wins
					winner := uint8(3 - leaverCamp)
					room.Battle.ForceEnd(winner)
					log.Printf("[battle] 🏳️ camp%d all left, camp%d wins by forfeit", leaverCamp, winner)
				}
				return c.Send(exitFrame)
			}

			// Battle already finished (settlement screen)
			room.State = 0
			c.roomMgr.ResetLoaded(room.ID)
			if exitType == 3 {
				// THOÁT → exit to lobby/hall and leave room
				_, newOwner := c.roomMgr.RemoveMemberWithTransfer(charID)
				c.roomID = 0
				remaining := c.roomMgr.GetMembers(room.ID)
				if len(remaining) > 0 {
					opFrame := protocol.EncodeNotifyRoomOp(1, charID, 0)
					c.broadcast.SendToAll(remaining, 0, opFrame)
					if newOwner != 0 {
						ownerFrame := protocol.EncodeNotifyRoomOp(26, newOwner, newOwner)
						c.broadcast.SendToAll(remaining, 0, ownerFrame)
						log.Printf("[%s] transferred room %d ownership to %d", c.role, room.ID, newOwner)
					}
				}
				return c.Send(exitFrame)
			}
			// VỀ → return to room (stay in room, broadcast 1707 so others see "%d đã về")
			members := c.roomMgr.GetMembers(room.ID)
			c.broadcast.SendToAll(members, 0, exitFrame)
			return nil
		}
		return c.Send(exitFrame)

	// === Quest System ===
	case protocol.MsgRequestQuestComplete: // 280 — complete quest
		if len(body) < 8 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		questID, _ := r.GetU32()
		choice, _ := r.GetU32()
		log.Printf("[gate] quest complete: quest=%d choice=%d", questID, choice)
		q := c.questMgr.CompleteQuest(c.session.CharID, questID, choice)
		if q == nil {
			return c.Send(protocol.EncodeNotifyQuestFailed(questID))
		}
		// Send quest update + currency update (reward coins)
		c.store.AddCurrency(c.session.CharID, 100, 50, 0) // +100 xu, +50 bạc per quest
		p := c.store.GetCharacter(c.session.CharID)
		qd := protocol.QuestData{QuestID: q.QuestID, State: q.State, Count: q.Count, Field3: q.Field3, Field4: q.Field4, Field5: q.Field5, Field6: q.Field6}
		frames := [][]byte{
			protocol.EncodeNotifyQuestUpdate(qd),
			protocol.EncodeNotifyQuestRemove([]uint32{questID}),
		}
		if p != nil {
			frames = append(frames, protocol.EncodeNotifyCharCurrency(&protocol.CharCurrency{
				Cash: p.Cash, Golden: p.Golden, Silver: p.Silver,
			}))
		}
		return c.SendMulti(frames...)

	case protocol.MsgRequestQuestOpenUI: // 281 — quest open UI check
		if len(body) < 1 || c.session == nil {
			return nil
		}
		uiID := body[0]
		log.Printf("[gate] quest open UI: ui=%d", uiID)
		updated := c.questMgr.NotifyOpenUI(c.session.CharID, uiID)
		for _, q := range updated {
			qd := protocol.QuestData{QuestID: q.QuestID, State: q.State, Count: q.Count, Field3: q.Field3, Field4: q.Field4, Field5: q.Field5, Field6: q.Field6}
			c.Send(protocol.EncodeNotifyQuestUpdate(qd))
		}
		return nil

	case protocol.MsgRequestRandQuestSwitch: // 285 — switch random quest
		if len(body) < 4 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		questID, _ := r.GetU32()
		log.Printf("[gate] rand quest switch: quest=%d", questID)
		// For now, just acknowledge — no random quest pool implemented yet
		return nil

	case protocol.MsgRequestStageReap: // 74 — reap stage reward
		if len(body) < 5 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		stageID, _ := r.GetU32()
		show, _ := r.GetU8()
		log.Printf("[gate] stage reap: stage=%d show=%d", stageID, show)
		result, ok := c.questMgr.ReapStage(c.session.CharID, stageID)
		if !ok {
			return nil
		}
		// Send reward and update
		c.store.AddCurrency(c.session.CharID, 200, 100, 0) // milestone reward
		p := c.store.GetCharacter(c.session.CharID)
		frames := [][]byte{
			protocol.EncodeNotifyStageReaped(result, stageID),
			protocol.EncodeNotifyStageClear(stageID),
		}
		if p != nil {
			frames = append(frames, protocol.EncodeNotifyCharCurrency(&protocol.CharCurrency{
				Cash: p.Cash, Golden: p.Golden, Silver: p.Silver,
			}))
		}
		return c.SendMulti(frames...)

	// === Sign-in (Điểm danh) ===
	case protocol.MsgRequestSignToday: // 360 — sign in today
		if c.session == nil {
			return nil
		}
		log.Printf("[gate] sign-in today for char %d", c.session.CharID)
		d, isNew := c.signMgr.SignToday(c.session.CharID)
		frames := [][]byte{
			protocol.EncodeNotifySignInInfo(d.Flag, d.VipFlag, d.Year, d.Month, d.Day, d.Count, d.Stage),
		}
		if !isNew {
			log.Printf("[gate] already signed today")
		} else {
			var rewards []game.GrantedReward
			if c.itemCatalog != nil {
				vnLoc := time.FixedZone("VN", 7*3600)
				weekday := int(time.Now().In(vnLoc).Weekday()) // 0=Sun..6=Sat
				rewards = c.itemCatalog.GetSignInDailyRewards(weekday)
			}
			if len(rewards) == 0 {
				rewards = []game.GrantedReward{{Kind: "currency", CurrName: "silver", Quantity: 5000}}
			}
			frames = append(frames, c.grantRewardsFrames(c.session.CharID, rewards, 0, 0, "", 0, false)...)
		}
		return c.SendMulti(frames...)

	case protocol.MsgRequestSignMark: // 361 — claim sign-in milestone
		if len(body) < 4 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		days, _ := r.GetU32()
		log.Printf("[gate] sign-in mark claim: days=%d", days)
		d, ok := c.signMgr.ClaimMark(c.session.CharID, days)
		if !ok || d == nil {
			return nil
		}
		var rewards []game.GrantedReward
		if c.itemCatalog != nil {
			rewards = c.itemCatalog.GetSignInMarkRewards(days)
		}
		if len(rewards) == 0 {
			rewards = []game.GrantedReward{
				{Kind: "currency", CurrName: "gift", Quantity: 50},
				{Kind: "currency", CurrName: "silver", Quantity: 10000},
			}
		}
		frames := [][]byte{
			protocol.EncodeNotifySignInInfo(d.Flag, d.VipFlag, d.Year, d.Month, d.Day, d.Count, d.Stage),
		}
		frames = append(frames, c.grantRewardsFrames(c.session.CharID, rewards, 0, 0, "", 0, false)...)
		return c.SendMulti(frames...)

	case protocol.MsgRequestSignVip: // 362 — VIP sign in
		if c.session == nil {
			return nil
		}
		log.Printf("[gate] VIP sign-in for char %d", c.session.CharID)
		d, isNew := c.signMgr.SignVip(c.session.CharID)
		frames := [][]byte{
			protocol.EncodeNotifySignInInfo(d.Flag, d.VipFlag, d.Year, d.Month, d.Day, d.Count, d.Stage),
		}
		if !isNew {
			log.Printf("[gate] already VIP signed today")
		} else {
			var rewards []game.GrantedReward
			if c.itemCatalog != nil {
				vipLv := uint8(1)
				if ch := c.store.GetCharacter(c.session.CharID); ch != nil && ch.VipLevel > 0 {
					vipLv = ch.VipLevel
				}
				rewards = c.itemCatalog.GetSignInVipRewards(vipLv)
			}
			if len(rewards) == 0 {
				rewards = []game.GrantedReward{{Kind: "currency", CurrName: "silver", Quantity: 5000}}
			}
			frames = append(frames, c.grantRewardsFrames(c.session.CharID, rewards, 0, 0, "", 0, false)...)
		}
		return c.SendMulti(frames...)

	case protocol.MsgRequestCashbackPick: // 80 — cashback pick
		if c.session == nil {
			return nil
		}
		log.Printf("[gate] cashback pick for char %d", c.session.CharID)
		// Give daily cashback reward
		c.store.AddCurrency(c.session.CharID, 100, 0, 0)
		p := c.store.GetCharacter(c.session.CharID)
		var frames [][]byte
		frames = append(frames, protocol.EncodeNotifyCashbackInfo(0, 0))
		if p != nil {
			frames = append(frames, protocol.EncodeNotifyCharCurrency(&protocol.CharCurrency{
				Cash: p.Cash, Golden: p.Golden, Silver: p.Silver,
			}))
		}
		return c.SendMulti(frames...)

	// === Sell/Swap Items ===
	case protocol.MsgRequestSwapItem: // 150 — swap item position
		if len(body) < 10 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		contType, _ := r.GetU32()
		origin, _ := r.GetI16()
		dest, _ := r.GetI16()
		count, _ := r.GetI32()
		log.Printf("[gate] swap item: cont=%d origin=%d dest=%d count=%d", contType, origin, dest, count)
		c.store.SwapItem(c.session.CharID, uint8(contType), origin, dest)
		return c.Send(c.encodeItemList(contType, 1))

	case protocol.MsgRequestSellItem: // 151 — sell item
		if len(body) < 6 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		contType, _ := r.GetU32()
		slot, _ := r.GetI16()
		log.Printf("[gate] sell item: cont=%d slot=%d", contType, slot)
		sellPrice := c.store.SellItem(c.session.CharID, uint8(contType), slot)
		if sellPrice > 0 {
			c.store.AddCurrency(c.session.CharID, sellPrice, 0, 0)
		}
		p := c.store.GetCharacter(c.session.CharID)
		bagFrame := c.encodeItemList(contType, 1)
		var frames [][]byte
		frames = append(frames, bagFrame)
		if p != nil {
			frames = append(frames, protocol.EncodeNotifyCharCurrency(&protocol.CharCurrency{
				Cash: p.Cash, Golden: p.Golden, Silver: p.Silver,
			}))
		}
		return c.SendMulti(frames...)

	// === Talent System ===
	case protocol.MsgRequestAddTalentPage: // 420
		if c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		pageName, _ := r.GetUTF8()
		buyType, _ := r.GetU8()
		log.Printf("[gate] talent add page: name=%s buyType=%d", pageName, buyType)
		page := c.talentMgr.AddPage(c.session.CharID, pageName, buyType)
		if page == nil {
			return nil
		}
		pPage := &protocol.TalentPage{UUID: page.UUID, Name: page.Name, CreateTime: page.CreateTime}
		pPage.Tree = make([]protocol.TalentGrid, len(page.Tree))
		for i, g := range page.Tree {
			pPage.Tree[i] = protocol.TalentGrid{TalentID: g.TalentID, Level: g.Level}
		}
		return c.Send(protocol.EncodeNotifyUpdateTalentPage(game.TalentOpAdd, pPage))

	case protocol.MsgRequestSaveTalentPage: // 421
		if c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		pPage, err := protocol.DecodeTalentPage(r)
		if err != nil {
			log.Printf("[gate] decode save talent page error: %v", err)
			return nil
		}
		log.Printf("[gate] talent save page: uuid=%s name=%s tree=%d", pPage.UUID, pPage.Name, len(pPage.Tree))
		gamePage := game.TalentPage{UUID: pPage.UUID, Name: pPage.Name, CreateTime: pPage.CreateTime}
		gamePage.Tree = make([]game.TalentGrid, len(pPage.Tree))
		for i, g := range pPage.Tree {
			gamePage.Tree[i] = game.TalentGrid{TalentID: g.TalentID, Level: g.Level}
		}
		saved := c.talentMgr.SavePage(c.session.CharID, gamePage)
		if saved == nil {
			return nil
		}
		respPage := &protocol.TalentPage{UUID: saved.UUID, Name: saved.Name, CreateTime: saved.CreateTime}
		respPage.Tree = make([]protocol.TalentGrid, len(saved.Tree))
		for i, g := range saved.Tree {
			respPage.Tree[i] = protocol.TalentGrid{TalentID: g.TalentID, Level: g.Level}
		}
		return c.Send(protocol.EncodeNotifyUpdateTalentPage(game.TalentOpSave, respPage))

	case protocol.MsgRequestOpTalentPage: // 422
		if len(body) < 8 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		opType, _ := r.GetU32()
		pageUUID, _ := r.GetUTF8()
		tankUUID, _ := r.GetUTF8()
		log.Printf("[gate] talent op: type=%d page=%s tank=%s", opType, pageUUID, tankUUID)

		switch opType {
		case game.TalentOpReset: // 3
			if c.talentMgr.ResetPage(c.session.CharID, pageUUID) {
				return c.Send(protocol.EncodeNotifyOpTalentPage(game.TalentOpReset, pageUUID))
			}
		case game.TalentOpDel: // 4
			if c.talentMgr.DeletePage(c.session.CharID, pageUUID) {
				return c.Send(protocol.EncodeNotifyOpTalentPage(game.TalentOpDel, pageUUID))
			}
		case game.TalentOpSetCur: // 5 — equip page to tank
			// Update tank's talPageUuid
			if tankUUID != "" {
				c.store.SetTankTalentPage(c.session.CharID, tankUUID, pageUUID)
				// Send 1151 with opType=20 (TALENT_TANK_OP)
				tank := c.store.GetTankByUUID(c.session.CharID, tankUUID)
				if tank != nil {
					return c.Send(protocol.EncodeUpdateTankInstance(toProtocolTank(tank), 20))
				}
			}
		case game.TalentOpAllPage: // 6 — request all pages
			data := c.talentMgr.GetTalentInfo(c.session.CharID)
			pages := make([]protocol.TalentPage, len(data.Pages))
			for i, p := range data.Pages {
				pages[i] = protocol.TalentPage{UUID: p.UUID, Name: p.Name, CreateTime: p.CreateTime}
				pages[i].Tree = make([]protocol.TalentGrid, len(p.Tree))
				for j, g := range p.Tree {
					pages[i].Tree[j] = protocol.TalentGrid{TalentID: g.TalentID, Level: g.Level}
				}
			}
			return c.Send(protocol.EncodeNotifyTalentInfo(pages, data.TotalPoint, data.BuyPageCount))
		case game.TalentOpCopy: // 7
			// Copy: create new page from share code (simplified: just add an empty page)
			page := c.talentMgr.AddPage(c.session.CharID, "Bản sao", 0)
			if page != nil {
				pPage := &protocol.TalentPage{UUID: page.UUID, Name: page.Name, CreateTime: page.CreateTime}
				return c.Send(protocol.EncodeNotifyUpdateTalentPage(game.TalentOpAdd, pPage))
			}
		}
		return nil

	// === Crystal System ===
	case protocol.MsgRequestCrystalSchemeInfo: // 423
		if c.session == nil {
			return nil
		}
		log.Printf("[gate] crystal request schemes")
		schemes := c.crystalMgr.GetSchemes(c.session.CharID)
		names := c.crystalMgr.GetNames(c.session.CharID)
		freeAt := c.crystalMgr.GetFreeAt(c.session.CharID)
		wireSchemes := make([]protocol.CrystalSchemeInfo, len(schemes))
		for i, s := range schemes {
			wireSchemes[i] = protocol.CrystalSchemeInfo{SchemeID: s.SchemeID, Slots: s.Slots}
		}
		return c.SendMulti(
			protocol.EncodeNotifyCrystalSchemeInfo(wireSchemes),
			protocol.EncodeNotifyCrystalSchemeNames(names),
			protocol.EncodeNotifyCrystalMakeFreeCoolTime(freeAt),
		)

	case protocol.MsgRequestSaveCrystalScheme: // 424
		if c.session == nil {
			return nil
		}
		scheme, err := protocol.DecodeSaveCrystalScheme(body)
		if err != nil {
			log.Printf("[gate] decode save crystal scheme error: %v", err)
			return nil
		}
		log.Printf("[gate] crystal save scheme: id=%d", scheme.SchemeID)
		c.crystalMgr.SaveScheme(c.session.CharID, scheme.SchemeID, scheme.Slots)
		// Re-send all schemes
		schemes := c.crystalMgr.GetSchemes(c.session.CharID)
		wireSchemes := make([]protocol.CrystalSchemeInfo, len(schemes))
		for i, s := range schemes {
			wireSchemes[i] = protocol.CrystalSchemeInfo{SchemeID: s.SchemeID, Slots: s.Slots}
		}
		return c.Send(protocol.EncodeNotifyCrystalSchemeInfo(wireSchemes))

	case protocol.MsgRequestRenameCrystalScheme: // 425
		if c.session == nil {
			return nil
		}
		schemeID, name, err := protocol.DecodeRenameCrystalScheme(body)
		if err != nil {
			return nil
		}
		log.Printf("[gate] crystal rename: scheme=%d name=%s", schemeID, name)
		ok := c.crystalMgr.RenameScheme(c.session.CharID, schemeID, name)
		result := uint32(0) // success
		if !ok {
			result = 1 // fail
		}
		return c.SendMulti(
			protocol.EncodeNotifyRenameCrystalResult(result),
			protocol.EncodeNotifyCrystalSchemeNames(c.crystalMgr.GetNames(c.session.CharID)),
		)

	case protocol.MsgRequestCrystalForge: // 426
		if c.session == nil {
			return nil
		}
		sell, items, err := protocol.DecodeCrystalForge(body)
		if err != nil {
			return nil
		}
		log.Printf("[gate] crystal forge: sell=%v count=%d", sell, len(items))
		ok := c.crystalMgr.ForgeResult(c.session.CharID, sell, items)
		result := uint32(0) // success
		if !ok {
			result = 1
		}
		return c.Send(protocol.EncodeNotifyUpgradeCrystalResult(result))

	case protocol.MsgRequestSetCurCrystalScheme: // 427
		if c.session == nil {
			return nil
		}
		schemeID, tankUUID, err := protocol.DecodeSetCurCrystalScheme(body)
		if err != nil {
			return nil
		}
		log.Printf("[gate] crystal set current scheme: scheme=%d tank=%s", schemeID, tankUUID)
		// Update tank's crystal scheme
		if tankUUID != "" {
			c.store.SetTankCrystalScheme(c.session.CharID, tankUUID, uint8(schemeID))
			tank := c.store.GetTankByUUID(c.session.CharID, tankUUID)
			if tank != nil {
				return c.Send(protocol.EncodeUpdateTankInstance(toProtocolTank(tank), 8))
			}
		}
		return nil

	case protocol.MsgRequestCrystalMake: // 430
		if c.session == nil {
			return nil
		}
		kind, err := protocol.DecodeCrystalMake(body)
		if err != nil {
			return nil
		}
		log.Printf("[gate] crystal make: kind=%d", kind)
		coolAt := c.crystalMgr.CrystalMake(c.session.CharID, kind)
		return c.Send(protocol.EncodeNotifyCrystalMakeFreeCoolTime(coolAt))

	// === Mail System ===
	case protocol.MsgRequestSendMail: // 270
		if c.session == nil {
			return nil
		}
		receiver, title, text, err := protocol.DecodeSendMail(body)
		if err != nil {
			log.Printf("[gate] decode send mail error: %v", err)
			return nil
		}
		log.Printf("[gate] send mail: to=%s title=%s", receiver, title)
		// Find receiver by name
		receiverChar := c.store.GetActiveCharacterByUsername(receiver)
		if receiverChar == nil {
			return c.Send(protocol.EncodeNotifyMailOperateResult(0, 3, ""))
		}
		c.mailMgr.SendMail(c.session.CharID, c.session.Character.Name, receiverChar.CharID, title, text)
		return c.Send(protocol.EncodeNotifyMailOperateResult(1, 3, ""))

	case protocol.MsgRequestMailOperate: // 271
		if c.session == nil {
			return nil
		}
		mailUUID, opType, err := protocol.DecodeRequestMailOperate(body)
		if err != nil {
			return nil
		}
		log.Printf("[gate] mail op: uuid=%s op=%d", mailUUID, opType)
		charID := c.session.CharID

		switch opType {
		case game.MailOpOpenBox: // 1 — request mail list
			mails := c.mailMgr.GetMailList(charID)
			briefs := make([]protocol.MailBriefInfo, len(mails))
			for i, m := range mails {
				briefs[i] = protocol.MailBriefInfo{
					UUID: m.UUID, SenderUUID: m.SenderUUID, Sender: m.Sender,
					Title: m.Title, ArriveTime: m.ArriveTime, MailType: m.MailType,
					MailState: m.MailState, SendMode: m.SendMode,
					AffixSign: m.AffixSign, CreateTime: m.CreateTime,
				}
			}
			return c.Send(protocol.EncodeNotifyMailList(briefs))

		case game.MailOpRead: // 4 — read mail
			mail := c.mailMgr.ReadMail(charID, mailUUID)
			if mail == nil {
				return c.Send(protocol.EncodeNotifyMailOperateResult(0, 4, mailUUID))
			}
			return c.SendMulti(
				protocol.EncodeNotifyMailInsideInfo(mail.UUID, mail.Text, 0),
				protocol.EncodeNotifyMailOperateResult(1, 4, mailUUID),
			)

		case game.MailOpDelete: // 5 — delete
			if mailUUID != "" {
				if c.mailMgr.DeleteMail(charID, mailUUID) {
					return c.Send(protocol.EncodeNotifyMailOperateResult(1, 5, mailUUID))
				}
				return c.Send(protocol.EncodeNotifyMailOperateResult(0, 5, mailUUID))
			}
			// Delete all read mails
			c.mailMgr.DeleteReadMails(charID)
			return c.Send(protocol.EncodeNotifyMailOperateResult(1, 5, ""))

		case game.MailOpPickupItem: // 8 — claim
			return c.Send(protocol.EncodeNotifyMailOperateResult(1, 8, mailUUID))
		}
		return nil

	case protocol.MsgRequestClaimMailItem: // 272
		if c.session == nil {
			return nil
		}
		mailUUID, _, err := protocol.DecodeClaimMailItem(body)
		if err != nil {
			return nil
		}
		log.Printf("[gate] claim mail item: mail=%s", mailUUID)
		return c.Send(protocol.EncodeNotifyMailOperateResult(1, 8, mailUUID))

	// === PvE Extended ===
	case protocol.MsgRequestSelectTutorMap: // 304
		if len(body) < 4 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		mapID, _ := r.GetU32()
		log.Printf("[gate] select tutor map: map=%d", mapID)
		// TODO: start PvE battle
		return nil

	case protocol.MsgRequestResetMapEnterCount: // 306
		if len(body) < 4 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		mapID, _ := r.GetU32()
		log.Printf("[gate] reset map enter: map=%d", mapID)
		return nil

	case protocol.MsgRequestSweepSoloMap: // 307
		if len(body) < 8 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		cityID, _ := r.GetU32()
		count, _ := r.GetU32()
		log.Printf("[gate] sweep solo: city=%d count=%d", cityID, count)
		// Return empty sweep awards
		return nil

	case protocol.MsgRequestPveRecord: // 558
		if len(body) < 4 || c.session == nil {
			return nil
		}
		r := protocol.NewReader(body)
		mapID, _ := r.GetU32()
		log.Printf("[gate] pve record: map=%d", mapID)
		return c.Send(protocol.EncodeNotifyPveRecord(mapID))

	default:
		log.Printf("[%s] unhandled msg %d (%d bytes)", c.role, msgID, len(body))
		return nil
	}
}

func (c *WSConn) handleVersion(body []byte) error {
	msg, err := protocol.DecodeRequestProtocolVersion(body)
	if err != nil {
		return fmt.Errorf("decode version: %w", err)
	}
	log.Printf("[%s] version handshake: auth=%d gate=%d ver=%s",
		c.role, msg.AuthVer, msg.GateVer, msg.ClientVer)

	return c.Send(protocol.EncodeVersionOk(msg.AuthVer, msg.GateVer, msg.MixAuth))
}

// handleAuthLogin handles message 51 on the login role → responds with 901 + 906
func (c *WSConn) handleAuthLogin(body []byte) error {
	if c.role != "login" {
		return fmt.Errorf("auth login on wrong role: %s", c.role)
	}

	msg, err := protocol.DecodeRequestAuthLogin(body)
	if err != nil {
		return fmt.Errorf("decode auth login: %w", err)
	}

	log.Printf("[login] auth login: user=%s sid=%d", msg.Name, msg.ClientSid)

	char := c.store.GetActiveCharacterByUsername(msg.Name)
	if char == nil {
		return c.Send(protocol.EncodeLoginFail(-1, "Tài khoản không tồn tại."))
	}

	sess := c.store.CreateSession(char)
	c.session = sess

	log.Printf("[login] session created: key=%d charID=%d", sess.SessionKey, sess.CharID)

	// Send LoginOk (901)
	loginOk := protocol.EncodeLoginOk(
		sess.SessionKey,
		uint32(sess.ExpiresAt.Unix()),
		1, // has_char
		sess.CharID,
	)

	// Send RegionServerList (906)
	regionList := protocol.EncodeRegionServerList([]protocol.RegionInfo{
		{
			RegionID:   299001,
			RegionName: "BangBang",
			GateRealm:  "127.0.0.1",
			GatePort:   8080,
			CommRealm:  "127.0.0.1",
			CommPort:   8080,
			CurLoad:    1,
			IsPvP:      1,
			OpenTime:   0,
		},
	})

	return c.SendMulti(loginOk, regionList)
}

func toProtocolTank(t *game.PlayerTank) *protocol.TankInstance {
	if t == nil {
		return nil
	}
	return &protocol.TankInstance{
		TankUuid:       t.TankUuid,
		TankID:         t.TankID,
		TankLevel:      t.TankLevel,
		TankExp:        t.TankExp,
		ExtFlag:        t.ExtFlag,
		StthLevel:      t.StthLevel,
		ExternalID:     t.ExternalID,
		WarCount:       t.WarCount,
		WeekWarCount:   t.WeekWarCount,
		ContType:       t.ContType,
		ExistTime:      t.ExistTime,
		HaloID:         t.HaloID,
		OwnTime:        t.OwnTime,
		ProficiencyVal: t.ProficiencyVal,
		BattleGains:    t.BattleGains,
		TalPageUuid:    t.TalPageUuid,
	}
}

func toProtocolItem(it *game.PlayerItem) *protocol.ItemInstance {
	if it == nil {
		return nil
	}
	return &protocol.ItemInstance{
		ItemUuid:   it.ItemUuid,
		TemplateID: it.TemplateID,
		SlotNo:     it.SlotNo,
		Count:      it.Count,
		Level:      it.Level,
		UpLevel:    it.UpLevel,
		Exp:        it.Exp,
		Rank:       it.Rank,
		ExtFlag:    it.ExtFlag,
		LifeTime:   it.LifeTime,
		CreateTime: it.CreateTime,
	}
}

// encodeTankList serializes the player's tank roster with full levels, strengthen, etc.
func (c *WSConn) encodeTankList(notifyType, contType uint8) []byte {
	if c.session == nil || c.session.Character == nil {
		return nil
	}
	p := c.session.Character
	var tanks []protocol.TankInstance
	for _, t := range p.Tanks {
		tanks = append(tanks, protocol.TankInstance{
			TankUuid:       t.TankUuid,
			TankID:         t.TankID,
			TankLevel:      t.TankLevel,
			TankExp:        t.TankExp,
			ExtFlag:        t.ExtFlag,
			StthLevel:      t.StthLevel,
			ExternalID:     t.ExternalID,
			WarCount:       t.WarCount,
			WeekWarCount:   t.WeekWarCount,
			ContType:       t.ContType,
			ExistTime:      t.ExistTime,
			HaloID:         t.HaloID,
			OwnTime:        t.OwnTime,
			StthCount:      t.StthCount,
			TalPageUuid:    t.TalPageUuid,
			ProficiencyVal: t.ProficiencyVal,
			BattleGains:    t.BattleGains,
		})
	}
	return protocol.EncodeNotifyTankList(notifyType, contType, tanks)
}

// encodeItemList serializes items in a specific bag container.
func (c *WSConn) encodeItemList(contType uint32, notifyType uint8) []byte {
	if c.session == nil || c.session.Character == nil {
		return nil
	}
	items := c.store.GetPlayerItems(c.session.CharID, uint8(contType))
	var protoItems []protocol.ItemInstance
	for _, it := range items {
		protoItems = append(protoItems, protocol.ItemInstance{
			ItemUuid:   it.ItemUuid,
			TemplateID: it.TemplateID,
			LifeTime:   it.LifeTime,
			ExtFlag:    it.ExtFlag,
			Count:      it.Count,
			Level:      it.Level,
			UpLevel:    it.UpLevel,
			Exp:        it.Exp,
			Rank:       it.Rank,
			UpCost:     it.UpCost,
			RankCost:   it.RankCost,
			CreateTime: it.CreateTime,
			SlotNo:     it.SlotNo,
		})
	}
	return protocol.EncodeNotifyItemList(contType, notifyType, protoItems)
}

// handleServerLogin handles message 54 on the gate role.
func (c *WSConn) handleServerLogin(body []byte) error {
	if c.role != "gate" {
		return fmt.Errorf("server login on wrong role: %s", c.role)
	}

	msg, err := protocol.DecodeRequestServerLogin(body)
	if err != nil {
		return fmt.Errorf("decode server login: %w", err)
	}

	log.Printf("[gate] server login: session=%d acctID=%d", msg.Session, msg.AcctID)

	sess := c.store.GetSession(msg.Session)
	if sess == nil || sess.CharID != msg.AcctID {
		return c.Send(protocol.EncodeLoginFail(-1, "Phiên đăng nhập không hợp lệ."))
	}
	c.session = sess

	p := sess.Character
	avID := p.AvatarID
	if avID == 0 {
		avID = 2801001
	}

	// 1014: Char list
	charList := protocol.EncodeNotifyCharList([]protocol.CharPickInfo{
		{
			Basic: protocol.CharBasic{
				AccountOid: p.CharID,
				Sexes:      1,
				Level:      p.Level,
				Exp:        p.Exp,
				AvatarID:   avID,
				Thew:       int16(p.Thew),
				CreateTime: uint32(p.Created.Unix()),
				Name:       p.Name,
				CharUuid:   p.CharUuid,
			},
			CharUuid: p.CharUuid,
		},
	})

	// 1005: World enter confirm
	enterConfirm := protocol.EncodeWorldEnterConfirm(p.CharID, sess.SessionKey)

	// 1016: Char data
	basic := protocol.CharBasic{
		AccountOid: p.CharID,
		Sexes:      1,
		Level:      p.Level,
		Exp:        p.Exp,
		AvatarID:   avID,
		Thew:       int16(p.Thew),
		ThewBuy:    0,
		CreateTime: uint32(p.Created.Unix()),
		OnlineTime: uint32(time.Now().Unix()),
		Name:       p.Name,
		CharUuid:   p.CharUuid,
		GmLevel:    0,
	}
	currency := protocol.CharCurrency{
		Cash:    p.Cash,
		Golden:  p.Golden,
		Silver:  p.Silver,
		Honor:   0,
		Crystal: 0,
	}
	technoVec := make([]int32, 11)
	charData := protocol.EncodeNotifyCharData(&basic, &currency, "", technoVec)

	// Additional init data
	firstCharge := protocol.EncodeNotifyFirstCharge(0)
	protectInfo := protocol.EncodeNotifyCharProtectInfo(0, 0)

	// 1150: Tank roster with full stats and levels
	tankList := c.encodeTankList(1, 0)

	// 1100: Bags (cont 2: VP, cont 3: Nguyên liệu, cont 4: Thời trang, cont 6: Skin, cont 7: Decor)
	bag2 := c.encodeItemList(2, 1)
	bag3 := c.encodeItemList(3, 1)
	bag4 := c.encodeItemList(4, 1)
	bag6 := c.encodeItemList(6, 1)
	bag7 := c.encodeItemList(7, 1)

	currencyUpdate := protocol.EncodeNotifyCharCurrency(&currency)
	settingFlag := protocol.EncodeNotifySettingFlag(c.store.GetSettingFlag(p.CharID))

	// Key binding / smartcast options (load saved data or default)
	charOption := protocol.EncodeNotifyCharOption(c.store.GetCharOption(p.CharID))

	// Register player as online and kick old session if already connected
	oldConn := c.broadcast.Register(p.CharID, c)
	if oldConn != nil && oldConn != c {
		log.Printf("[gate] ⚠️ char %d (%s) already connected! Kicking out previous session...", p.CharID, p.Name)
		kickFrame := protocol.EncodeCloseSessionConfirm(1) // 1 = session closed / logged in elsewhere
		_ = oldConn.Send(kickFrame)
		oldConn.Close()
	}

	c.onlineMgr.Add(&game.OnlinePlayer{
		CharID:   p.CharID,
		CharUUID: p.CharUuid,
		Name:     p.Name,
		Level:    p.Level,
		AvatarID: avID,
	})
	log.Printf("[gate] player %s (id=%d) is now online", p.Name, p.CharID)

	// === Quest / Sign-in / Metagame init ===
	c.questMgr.InitPlayer(p.CharID)

	// 1250: Quest list
	questEntries := c.questMgr.GetQuests(p.CharID)
	var questData []protocol.QuestData
	for _, q := range questEntries {
		questData = append(questData, protocol.QuestData{
			QuestID: q.QuestID, State: q.State, Count: q.Count,
			Field3: q.Field3, Field4: q.Field4, Field5: q.Field5, Field6: q.Field6,
		})
	}
	questList := protocol.EncodeNotifyQuestList(questData, 1) // kind=1 full replace

	// 1400: Sign-in info
	signData := c.signMgr.GetSignIn(p.CharID)
	signInfo := protocol.EncodeNotifySignInInfo(signData.Flag, signData.VipFlag,
		signData.Year, signData.Month, signData.Day, signData.Count, signData.Stage)

	// 1309: Stage progress (empty initial)
	stageProgress := protocol.EncodeNotifyStageProgress(0, nil, nil)

	// 1045: Limit list (empty initial)
	limitList := protocol.EncodeNotifyLimitList(nil)

	// 1049: VIP info (default zeros)
	vipInfo := protocol.EncodeNotifyVipInfo(0, 0, 0, 0, 0)

	// 81: Cashback info
	cashbackInfo := protocol.EncodeNotifyCashbackInfo(0, 0)

	// Talent: 1452 — full talent info on login
	talentData := c.talentMgr.GetTalentInfo(p.CharID)
	talPages := make([]protocol.TalentPage, len(talentData.Pages))
	for i, tp := range talentData.Pages {
		talPages[i] = protocol.TalentPage{UUID: tp.UUID, Name: tp.Name, CreateTime: tp.CreateTime}
		talPages[i].Tree = make([]protocol.TalentGrid, len(tp.Tree))
		for j, g := range tp.Tree {
			talPages[i].Tree[j] = protocol.TalentGrid{TalentID: g.TalentID, Level: g.Level}
		}
	}
	talentInfo := protocol.EncodeNotifyTalentInfo(talPages, talentData.TotalPoint, talentData.BuyPageCount)

	// Crystal: 1454 + 1455 + 1461 on login
	crystalSchemes := c.crystalMgr.GetSchemes(p.CharID)
	wireCrystals := make([]protocol.CrystalSchemeInfo, len(crystalSchemes))
	for i, s := range crystalSchemes {
		wireCrystals[i] = protocol.CrystalSchemeInfo{SchemeID: s.SchemeID, Slots: s.Slots}
	}
	crystalInfo := protocol.EncodeNotifyCrystalSchemeInfo(wireCrystals)
	crystalNames := protocol.EncodeNotifyCrystalSchemeNames(c.crystalMgr.GetNames(p.CharID))
	crystalCool := protocol.EncodeNotifyCrystalMakeFreeCoolTime(c.crystalMgr.GetFreeAt(p.CharID))

	// Mail: 1230 unread count on login
	mailUnread := protocol.EncodeNotifyNoReadMailCount(c.mailMgr.GetUnreadCount(p.CharID))

	// PvE: 1303 city info on login
	pveCities := c.pveMgr.GetCities(p.CharID)
	wirePveCities := make([]protocol.CityInfoWire, len(pveCities))
	for i, city := range pveCities {
		wirePveCities[i] = protocol.CityInfoWire{
			CityID: city.CityID, Value: city.Value,
			EvalEasy: city.EvalEasy, EvalDiff: city.EvalDiff,
			DiffPass: city.DiffPass, ResetTime: city.ResetTime,
		}
	}
	pveInfo := protocol.EncodeNotifyCityInfoInitFull(wirePveCities)

	return c.SendMulti(
		charList,       // 1014
		enterConfirm,   // 1005
		charData,       // 1016
		firstCharge,    // 1031
		protectInfo,    // 1033
		tankList,       // 1150
		bag2,           // 1100 (VP)
		bag3,           // 1100 (Nguyên liệu)
		bag4,           // 1100 (Thời trang)
		bag6,           // 1100 (Skin)
		bag7,           // 1100 (Decor)
		currencyUpdate, // 1039
		settingFlag,    // 1036
		charOption,     // 1047
		questList,      // 1250
		signInfo,       // 1400
		stageProgress,  // 1309
		limitList,      // 1045
		vipInfo,        // 1049
		cashbackInfo,   // 81
		talentInfo,     // 1452
		crystalInfo,    // 1454
		crystalNames,   // 1455
		crystalCool,    // 1461
		mailUnread,     // 1230
		pveInfo,        // 1303
	)
}

// handleWorldEnter handles message 56.
// grantRewardsFrames grants rewards to charID and builds the standard response frames:
// 1104 (NotifySettleAward popup), optional 1103 (item remove), 1102 (item add),
// optional 1100 (bag refresh), and 1039 (currency update).
func (c *WSConn) grantRewardsFrames(charID uint32, rewards []game.GrantedReward, contType uint32, slotNo int16, removedUUID string, remaining int32, refreshBag bool) [][]byte {
	addedItems := c.store.GrantBoxRewards(charID, rewards, c.itemCatalog)

	awardInfo := &protocol.SettleAwardInfo{}
	var awardItems []protocol.AwardItem
	var tankVec []uint32
	for _, r := range rewards {
		switch r.Kind {
		case "currency":
			switch r.CurrName {
			case "cash":
				awardInfo.Cash += r.Quantity
			case "gift":
				awardInfo.Gift += r.Quantity // xu khóa
			case "silver", "golden":
				awardInfo.Golden += r.Quantity // bạc
			}
		case "item":
			awardItems = append(awardItems, protocol.AwardItem{ItemID: r.ID, Count: r.Quantity})
		case "tank":
			tankVec = append(tankVec, r.ID)
		}
	}
	if len(awardItems) > 0 {
		awardInfo.Groups = []protocol.AwardGroup{{GroupType: 0, Items: awardItems}}
	}
	awardInfo.TankVec = tankVec

	frames := [][]byte{protocol.EncodeNotifySettleAward(0, awardInfo, 1, 0)}

	if refreshBag && remaining <= 0 && removedUUID != "" {
		frames = append(frames, protocol.EncodeNotifyItemRemove(contType, []int16{slotNo}, []string{removedUUID}))
	}

	for _, it := range addedItems {
		frames = append(frames, protocol.EncodeNotifyItemAdd(protocol.PlayerItemData{
			ItemUuid:   it.ItemUuid,
			ContType:   it.ContType,
			SlotNo:     it.SlotNo,
			TemplateID: it.TemplateID,
			Count:      it.Count,
			Level:      it.Level,
			UpLevel:    it.UpLevel,
			Exp:        it.Exp,
			Rank:       it.Rank,
			UpCost:     it.UpCost,
			RankCost:   it.RankCost,
			LifeTime:   it.LifeTime,
			ExtFlag:    it.ExtFlag,
			CreateTime: it.CreateTime,
		}))
	}

	if refreshBag {
		frames = append(frames, c.encodeItemList(contType, 1))
	}

	if ch := c.store.GetCharacter(charID); ch != nil {
		cur := protocol.CharCurrency{
			Cash:   ch.Cash,
			Golden: ch.Golden,
			Silver: ch.Silver,
		}
		frames = append(frames, protocol.EncodeNotifyCharCurrency(&cur))
	}
	return frames
}

func (c *WSConn) handleWorldEnter(body []byte) error {
	msg, err := protocol.DecodeWorldEnterMessage(body)
	if err != nil {
		return fmt.Errorf("decode world enter: %w", err)
	}
	log.Printf("[gate] world enter (already handled): char=%s", msg.CharUuid)
	return nil
}

// buildCharBrief builds a pre-encoded ROOM_CHAR_BRIEF for the current connection's character.
func (c *WSConn) buildCharBrief(camp uint8) []byte {
	p := c.session.Character
	var activeTank *game.PlayerTank
	for i := range p.Tanks {
		if p.Tanks[i].ExtFlag&2 != 0 {
			activeTank = &p.Tanks[i]
			break
		}
	}
	if activeTank == nil && len(p.Tanks) > 0 {
		activeTank = &p.Tanks[0]
	}
	var tankID uint32 = 10000019
	var tankLvl uint8 = 1
	var extID uint32 = 0
	if activeTank != nil {
		tankID = activeTank.TankID
		tankLvl = activeTank.TankLevel
		extID = activeTank.ExternalID
	}
	avID := p.AvatarID
	if avID == 0 {
		avID = 2801001
	}
	return protocol.EncodeRoomCharBrief(p.CharID, p.CharUuid, p.Name, p.Level, avID, tankID, tankLvl, extID, camp)
}
