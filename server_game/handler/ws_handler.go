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
	conn      *websocket.Conn
	mu        sync.Mutex
	store     *game.Store
	roomMgr   *game.RoomManager
	onlineMgr *game.OnlineTracker
	broadcast *game.Broadcaster
	session   *game.Session
	role      string // "login" or "gate"
	closed    bool
	roomID    uint32 // current room this connection is in (0 = none)
}

func NewWSConn(conn *websocket.Conn, store *game.Store, roomMgr *game.RoomManager, onlineMgr *game.OnlineTracker, broadcast *game.Broadcaster, role string) *WSConn {
	return &WSConn{
		conn:      conn,
		store:     store,
		roomMgr:   roomMgr,
		onlineMgr: onlineMgr,
		broadcast: broadcast,
		role:      role,
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
				c.roomMgr.RemoveMember(charID)
				if room != nil {
					// Broadcast leave (RoomOp 1 = leave) to remaining members
					leaveFrame := protocol.EncodeNotifyRoomOp(1, charID, charID)
					c.broadcast.SendToAll(room.Members, charID, leaveFrame)
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
		log.Printf("[gate] use item: cont=%d slot=%d count=%d", req.ContType, req.SlotNo, req.Count)
		if c.session == nil {
			return nil
		}
		_, p, err := c.store.UseItem(c.session.CharID, uint8(req.ContType), req.SlotNo, req.Count)
		if err != nil {
			log.Printf("[gate] use item error: %v", err)
			return nil
		}
		bagFrame := c.encodeItemList(req.ContType, 1)
		cur := protocol.CharCurrency{
			Cash:    p.Cash,
			Golden:  p.Golden,
			Silver:  p.Silver,
			Honor:   0,
			Crystal: 0,
		}
		curFrame := protocol.EncodeNotifyCharCurrency(&cur)
		return c.SendMulti(bagFrame, curFrame)

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
		log.Printf("[%s] set map: mapID=%d", c.role, mapID)
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
		// Create room in room manager
		room := c.roomMgr.CreateRoom(req.Name, req.BType, uint32(req.BMode), req.MapID, req.Password, p.CharID, creatorBrief)
		c.roomID = room.ID
		frame := protocol.EncodeEnterRoomOk(room.ID, p.CharID, req.Name, req.BType, uint32(req.BMode), req.MapID, req.Password, creatorBrief)
		log.Printf("[%s] room created: id=%d, name=%s, type=%d, map=%d", c.role, room.ID, req.Name, req.BType, req.MapID)
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
				c.roomMgr.RemoveMember(charID)
				c.roomID = 0
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
				log.Printf("[%s] 🚀 starting match for room %d (map=%d, %d players: %v)",
					c.role, room.ID, room.MapID, len(room.Members), room.Members)
				room.State = 1 // in-battle
				c.roomMgr.ResetLoaded(room.ID)
				briefs := c.roomMgr.GetMemberBriefs(room.ID)
				startFrame := protocol.EncodeNotifyStartGame(room.ID, room.MapID, room.Type, briefs, 0)
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
			c.roomMgr.SetMemberPos(room.ID, charID, int16(req.StartX), int16(req.StartY))
			syncFrame := protocol.EncodeSyncSceneMove(charID, int16(req.StartX), int16(req.StartY), 200, req.Direction, 0)
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
			startX, startY := c.roomMgr.GetMemberPos(room.ID, charID)
			bulletID := c.roomMgr.NextBulletID(room.ID)
			skills := c.roomMgr.GetMemberSkills(room.ID, charID)
			template := uint32(1)
			switch req.SlotNo {
			case 1:
				if skills[0] != 0 {
					template = skills[0]
				}
			case 2:
				if skills[1] != 0 {
					template = skills[1]
				}
			case 3:
				if skills[3] != 0 {
					template = skills[3]
				}
			}
			fireFrame := protocol.EncodeSyncSceneFire(bulletID, charID, startX, startY, req.DestX, req.DestY, 600, template)
			c.broadcast.SendToAll(room.Members, 0, fireFrame)
			log.Printf("[%s] player %d fired bullet %d (slot=%d, template=%d) from (%d,%d) to (%d,%d)", c.role, charID, bulletID, req.SlotNo, template, startX, startY, req.DestX, req.DestY)
		}
		return nil

	case protocol.MsgRequestExitBattleEnd:
		log.Printf("[%s] exit battle end requested", c.role)
		charID := uint32(0)
		if c.session != nil && c.session.Character != nil {
			charID = c.session.Character.CharID
		}
		room := c.roomMgr.GetRoom(c.roomID)
		if room == nil && charID != 0 {
			room = c.roomMgr.FindRoomByMember(charID)
		}
		if room != nil {
			room.State = 0
			c.roomMgr.ResetLoaded(room.ID)
		}
		return nil

	default:
		log.Printf("[%s] unhandled msg %d (%d bytes)", c.role, msgID, len(body))
		return nil
	}
}

// handleVersion handles message 52 → responds with 903
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
			TankUuid:        t.TankUuid,
			TankID:          t.TankID,
			TankLevel:       t.TankLevel,
			TankExp:         t.TankExp,
			ExtFlag:         t.ExtFlag,
			StthLevel:       t.StthLevel,
			ExternalID:      t.ExternalID,
			WarCount:        t.WarCount,
			WeekWarCount:    t.WeekWarCount,
			ContType:        t.ContType,
			ExistTime:       t.ExistTime,
			HaloID:          t.HaloID,
			OwnTime:         t.OwnTime,
			StthCount:       t.StthCount,
			TalPageUuid:     t.TalPageUuid,
			ProficiencyVal:  t.ProficiencyVal,
			BattleGains:     t.BattleGains,
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
	settingFlag := protocol.EncodeNotifySettingFlag(0)

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
	)
}

// handleWorldEnter handles message 56.
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

// startBattle transitions all players in a room into the battle arena.
func (c *WSConn) startBattle(room *game.Room) {
	members := c.roomMgr.GetMembers(room.ID)
	log.Printf("[battle] ⚔️ starting battle for room %d (map=%d, %d members: %v)", room.ID, room.MapID, len(members), members)

	// Gather TankBattleInfo for all members
	tanks := make([]*protocol.TankBattleInfo, 0, len(members))
	for idx, mid := range members {
		char := c.store.GetCharacter(mid)
		name := fmt.Sprintf("Player_%d", mid)
		var tankLvl uint8 = 1
		var activeTankID uint32 = 10000019
		if char != nil {
			name = char.Name
			var activeTank *game.PlayerTank
			for i := range char.Tanks {
				if char.Tanks[i].ExtFlag&2 != 0 {
					activeTank = &char.Tanks[i]
					break
				}
			}
			if activeTank == nil && len(char.Tanks) > 0 {
				activeTank = &char.Tanks[0]
			}
			if activeTank != nil {
				tankLvl = activeTank.TankLevel
				activeTankID = activeTank.TankID
			}
		}

		tankSkills := game.GetTankSkills(activeTankID)
		c.roomMgr.SetMemberSkills(room.ID, mid, tankSkills)

		camp := c.roomMgr.GetMemberCamp(room.ID, mid)

		var spawnX int16 = 250
		if camp == 2 {
			spawnX = 1150
		}
		spawnY := int16(350 + (idx%5)*80)
		c.roomMgr.SetMemberPos(room.ID, mid, spawnX, spawnY)

		tInfo := &protocol.TankBattleInfo{
			ObjID:       mid, // ObjID matches account_oid so tanks.has(self_id) in Godot client succeeds
			AcctOid:     mid,
			X:           spawnX,
			Y:           spawnY,
			HP:          1000,
			MaxHP:       1000,
			Star:        1,
			Camp:        camp,
			Name:        name,
			LifeCount:   3,
			BattleExp:   0,
			BattleLevel: 1,
			TankLevel:   tankLvl,
			MP:          100,
			MaxMP:       100,
			Shield:      0,
			Skills:      tankSkills,
		}
		tanks = append(tanks, tInfo)
	}

	now := uint32(time.Now().Unix())

	// For each member, send:
	// 1. NotifySelfData (1550) - their tank info
	// 2. NotifyOtherList (1551) - other players' tanks
	// 3. NotifyBattleEnter (1586) - battle start signal (triggers client.battle.started = true)
	for _, selfTank := range tanks {
		var others []*protocol.TankBattleInfo
		for _, other := range tanks {
			if other.ObjID != selfTank.ObjID {
				others = append(others, other)
			}
		}

		selfFrame := protocol.EncodeNotifySelfData(selfTank)
		otherFrame := protocol.EncodeNotifyOtherList(others)
		enterFrame := protocol.EncodeNotifyBattleEnter(now, 0)

		c.broadcast.SendTo(selfTank.ObjID, selfFrame)
		c.broadcast.SendTo(selfTank.ObjID, otherFrame)
		c.broadcast.SendTo(selfTank.ObjID, enterFrame)
		log.Printf("[battle] sent 1550, 1551, 1586 to player %d (%s, camp=%d)", selfTank.ObjID, selfTank.Name, selfTank.Camp)
	}
}
