package protocol

// Message IDs for the sixcube protocol.
// Client → Server (requests) and Server → Client (responses).
// Values extracted from protocol/message_ids.gd and battle_protocol/message_ids.gd.

const (
	// === Auth flow ===
	MsgRequestAuthLogin        int16 = 51  // C→S: login with username/token
	MsgRequestProtocolVersion  int16 = 52  // C→S: version handshake
	MsgRequestServerLogin      int16 = 54  // C→S: gate login with session
	MsgWorldEnterMessage       int16 = 56  // C→S: enter world with char uuid
	MsgRequestSwitchLine       int16 = 59  // C→S: switch line/channel

	// === System ===
	MsgSystemHeartBeat int16 = 60  // bidirectional heartbeat
	MsgRequestPing     int16 = 61  // C→S: ping
	MsgGmCommand       int16 = 62  // C→S: GM command

	// === Auth responses ===
	MsgLoginOk              int16 = 901  // S→C: login success
	MsgLoginFail            int16 = 902  // S→C: login fail
	MsgVersionOk            int16 = 903  // S→C: version accepted (raw 12-byte body)
	MsgVersionFail          int16 = 904  // S→C: version rejected
	MsgRegionServerList     int16 = 906  // S→C: server list
	MsgCloseSessionConfirm  int16 = 909  // S→C: session force-close (AuthMessage.CloseSessionConfirm)

	// === World ===
	MsgWorldEnterConfirm  int16 = 1005  // S→C: world enter OK
	MsgWorldEnterRejected int16 = 1006  // S→C: world enter rejected

	// === Character ===
	MsgNotifyCharList       int16 = 1014  // S→C: character list
	MsgNotifyCharData       int16 = 1016  // S→C: character data
	MsgNotifyCharExp        int16 = 1017  // S→C: exp update
	MsgNotifyCharProtectInfo int16 = 1033  // S→C: password protect info
	MsgNotifyFirstCharge    int16 = 1031  // S→C: first charge info
	MsgNotifySettingFlag    int16 = 1036  // S→C: setting flags
	MsgNotifyCharCurrency   int16 = 1039  // S→C: currency update
	MsgNotifyCharOption     int16 = 1047  // S→C: key binding / smartcast options (JSON utf8)

	// === Settings (C→S) ===
	MsgRequestChangeSetting  int16 = 79  // C→S: change setting flags (u32)
	MsgRequestSetCharOption  int16 = 88  // C→S: set key binding / smartcast options (utf8 JSON)

	// === Items & Bags ===
	MsgRequestSellItem      int16 = 151  // C→S: sell item
	MsgRequestCleanUpCont   int16 = 152  // C→S: clean up / sort bag
	MsgRequestUseItem       int16 = 153  // C→S: use item
	MsgRequestContainerItem int16 = 165  // C→S: request bag container items
	MsgNotifyItemList       int16 = 1100 // S→C: item list
	MsgNotifyItemSwap       int16 = 1101 // S→C: item swap
	MsgNotifyItemAdd        int16 = 1102 // S→C: item added
	MsgNotifyItemRemove     int16 = 1103 // S→C: items removed
	MsgNotifyItemFailed     int16 = 1113 // S→C: item use failed

	// === Tanks ===
	MsgRequestChangeBattleTank int16 = 200 // C→S: change active/battle tank
	MsgRequestLevelUpTank    int16 = 203  // C→S: level up tank
	MsgRequestStrengthenTank int16 = 204  // C→S: strengthen tank
	MsgNotifyTankList        int16 = 1150 // S→C: tank list
	MsgNotifyTankUpdate      int16 = 1151 // S→C: tank updated
	MsgNotifySkinChipList    int16 = 1163 // S→C: skin chip list

	// === Sprays ===
	MsgNotifySprayList int16 = 1115  // S→C: spray list

	// === Trade ===
	MsgRequestBuyGoods   int16 = 250   // C→S: buy goods from shop
	MsgBuyGoodsResult    int16 = 1041  // S→C: buy success
	MsgBuyGoodsFailed    int16 = 1042  // S→C: buy failed

	// === Friends ===
	MsgRequestFriendApplyList int16 = 755   // C→S: request friend apply list
	MsgNotifyFriendApplyList  int16 = 10002 // S→C: notify friend apply list
	MsgNotifyFriendApplyCount int16 = 10003 // S→C: notify friend apply count

	// === PVE & Boss ===
	MsgRequestSoloPveInfo int16 = 308  // C→S: PvE solo info request
	MsgNotifyCityInfoInit int16 = 1303 // S→C: PvE city info init
	MsgOpenBossActUI      int16 = 556  // C→S: open boss UI
	MsgCloseBossActUI     int16 = 557  // C→S: close boss UI
	MsgNotifyBossState    int16 = 1951 // S→C: boss activity state
	MsgNotifyBossSnapshot int16 = 1952 // S→C: boss snapshot (HP, rank)

	// === Surrender / Vote ===
	MsgRequestSurrenderVotation  int16 = 512  // C→S: request surrender vote (body: sceneId u32)
	MsgVoteSurrender             int16 = 513  // C→S: cast vote (body: agree u8 + sceneId u32)

	// === Rooms & Hall ===
	MsgRequestMoveForward    int16 = 501  // C→S: move forward
	MsgRequestUseSkill       int16 = 503  // C→S: use skill / shoot
	MsgRequestOpSpray        int16 = 507  // C→S: use spray paint
	MsgRequestSignalInfo     int16 = 511  // C→S: minimap signal (attack/retreat/rally)
	MsgRequestCreateRoom     int16 = 600  // C→S: create room
	MsgRequestJoinRoom       int16 = 601  // C→S: join room
	MsgRequestRoomOp         int16 = 602  // C→S: room operation (ready, camp, leave, kick, etc.)
	MsgRequestSetMap         int16 = 603  // C→S: set room map
	MsgRequestPlayerList     int16 = 604  // C→S: player list in hall
	MsgSyncLoadAndDelay      int16 = 605  // C→S: sync battle load rate and delay
	MsgRequestInHall         int16 = 607  // C→S: request hall display
	MsgRequestOutHall        int16 = 608  // C→S: player leaves hall
	MsgRequestStartMatch     int16 = 610  // C→S: start match
	MsgRequestStopMatch      int16 = 611  // C→S: stop match
	MsgRequestExitBattleEnd  int16 = 613  // C→S: exit battle end
	MsgNotifySelfData        int16 = 1550 // S→C: battle self tank info
	MsgNotifyOtherList       int16 = 1551 // S→C: battle other tanks list
	MsgNotifyAddBuff         int16 = 1558 // S→C: add buff to actor
	MsgNotifyRemoveBuff      int16 = 1559 // S→C: remove buff from actor
	MsgNotifyAttrChange      int16 = 1560 // S→C: sync actor attribute (1=speed, 4=fireInterval)
	MsgNotifySceneStat       int16 = 1561 // S→C: per-player battle stats (kills, deaths, assists, damage)
	MsgNotifyAddObject       int16 = 1556 // S→C: add scene object (Wukong space visuals, etc.)
	MsgSyncSceneData         int16 = 1564 // S→C: battle sync scene data (movement, fire, hp)
	MsgNotifySkillCoolTime   int16 = 1572 // S→C: skill/props cooldown update
	MsgNotifySwapSkill       int16 = 1579 // S→C: replace skill slot (e.g. Wukong empowered slot 0)
	MsgNotifyBuffUpdate      int16 = 1581 // S→C: update buff timer and stacks
	MsgNotifyBattleEnter     int16 = 1586 // S→C: notify enter battle (battle starts)
	MsgNotifyStopMove        int16 = 1554 // S→C: stop/snap move (instant halt/teleport)
	MsgEnterRoomOk           int16 = 1700 // S→C: enter room ok
	MsgNotifyRoomOp          int16 = 1701 // S→C: notify room operation
	MsgNotifyRoomAdd         int16 = 1702 // S→C: notify new player joined room
	MsgNotifyPlayerList      int16 = 1703 // S→C: notify player list
	MsgNotifyRoomMap         int16 = 1704 // S→C: notify room map changed
	MsgNotifyStartGame       int16 = 1705 // S→C: notify start game (enter battle)
	MsgNotifyLoadedRate      int16 = 1709 // S→C: notify player map load rate
	MsgNotifyHallDisplayList int16 = 1724 // S→C: notify hall display list
	MsgNotifyTankSelect      int16 = 1727 // S→C: notify tank changed in room
	MsgNotifyStartMatch      int16 = 1719 // S→C: notify match started (pairing timer)
	MsgNotifyStopMatch       int16 = 1720 // S→C: notify match stopped

	// === Quests ===
	MsgNotifyAcemList   int16 = 1256  // S→C: achievement list

	// === Honor ===
	MsgNotifyHonorList  int16 = 1029  // S→C: honor list
	MsgNotifyHonorEquip int16 = 1028  // S→C: honor equipped

	// === Activity ===
	MsgNotifyActList int16 = 1950  // S→C: activity list (raw binary)

	// === Chat ===
	MsgChatMessage int16 = 1510  // bidirectional chat

	// === Battle helper ===
	MsgNotifyBattleBooster int16 = 1056  // S→C: battle booster

	// === Surrender notifications ===
	MsgNotifyShowSurrenderVotation    int16 = 1597 // S→C: show vote panel (validCount u8, showEndTime u32, nextTime u32, sponsor u32)
	MsgUpdateVotationInfo             int16 = 1598 // S→C: update vote results (validCount u8, vecVoteInfo array[u16] of u8)
	MsgNotifySurrenderVotationCoolTime int16 = 1599 // S→C: cooldown time (nTime u32)

	// === Battle events ===
	MsgNotifyBorn          int16 = 1552  // S→C: respawn/born
	MsgNotifyRespawnTimer  int16 = 1553  // S→C: respawn countdown
	MsgNotifyKillInfo      int16 = 1566  // S→C: kill notification
	MsgNotifySpray         int16 = 1569  // S→C: spray paint display
	MsgNotifySignalInfo    int16 = 1594  // S→C: minimap signal notification
	MsgSyncHpChange        int16 = 1605  // S→C: damage/heal numbers (deltas for fly text)
	MsgNotifySettlement    int16 = 1708  // S→C: battle end settlement
	MsgNotifyCampKillNum   int16 = 1710  // S→C: camp kill count update
	MsgNotifyExitBattle    int16 = 1707  // S→C: exit battle / return to room or lobby
	MsgNotifyOccupyState   int16 = 1565  // S→C: occupy flag state snapshot
	MsgNotifyOccupyScore   int16 = 1732  // S→C: occupy flag score increment

	// === Room ===
	MsgRoomList int16 = 2203  // S→C: room list
)
