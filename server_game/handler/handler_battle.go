package handler

import (
	"fmt"
	"log"
	"math"
	"time"

	"bangbang-server/game"
	"bangbang-server/protocol"
)

// dispatchActionResult broadcasts fires, skills, moves, buffs, cooldowns, slot swaps and schedules delayed actions.
func (c *WSConn) dispatchActionResult(room *game.Room, charID, tankID uint32, slotNo uint8, res game.ActionResult) {
	if room == nil {
		return
	}
	if slotNo == 0 && room.Battle != nil && len(res.Fires) > 0 && res.Fires[0].Basic {
		extraFires, removeBuffs := room.Battle.ConsumeMapAmmoShot(charID, res.Fires[0])
		if len(extraFires) > 0 {
			res.Fires = append(res.Fires, extraFires...)
		}
		if len(removeBuffs) > 0 {
			res.Buffs = append(res.Buffs, removeBuffs...)
		}
	}
	for _, ev := range res.Fires {
		// Clip bullet destination to static map walls only (not destructible NPCs, which Tick() hits and blows up).
		destX, destY := ev.DestX, ev.DestY
		hitStatic := false
		if room.Battle != nil && ev.TargetID == 0 && len(room.Battle.Walls) > 0 {
			if hit, frac := game.SegmentHitsWall(room.Battle.Walls, float64(ev.StartX), float64(ev.StartY), float64(ev.DestX), float64(ev.DestY)); hit && frac <= 1.0 {
				hitStatic = true
				destX = ev.StartX + int16(math.Round(float64(ev.DestX-ev.StartX)*frac))
				destY = ev.StartY + int16(math.Round(float64(ev.DestY-ev.StartY)*frac))
			}
		}
		bulletID := c.roomMgr.NextBulletID(room.ID)
		fireFrame := protocol.EncodeSyncSceneFire(bulletID, charID, ev.StartX, ev.StartY, destX, destY, ev.Speed, ev.Template)
		c.broadcast.SendToAll(room.Members, 0, fireFrame)
		log.Printf("[%s] player %d (tank=%d) fired bullet %d (slot=%d, template=%d, speed=%d) from (%d,%d) to (%d,%d)", c.role, charID, tankID, bulletID, slotNo, ev.Template, ev.Speed, ev.StartX, ev.StartY, destX, destY)

		// Register bullet for collision tracking
		if room.Battle != nil {
			camp := c.roomMgr.GetMemberCamp(room.ID, charID)
			dx := float64(destX - ev.StartX)
			dy := float64(destY - ev.StartY)
			dist := math.Hypot(dx, dy)
			speedPPS := float64(ev.Speed) // pixels per second
			var lifeMS int64 = 3000       // default 3s max life
			if speedPPS > 0 {
				lifeMS = int64(dist / speedPPS * 1000)
				if lifeMS < 50 {
					lifeMS = 50
				}
				if lifeMS > 5000 {
					lifeMS = 5000
				}
			}
			// Determine damage school ("energy" vs "physical")
			school := ev.School
			if school == "" {
				if eff, ok := game.GetEffectTemplate(ev.Template); ok && eff.HarmType == 2 {
					school = "energy"
				} else {
					school = "physical"
				}
			}
			// Get attacker power & pierce snapshot for the resolved school
			var power float64 = 100
			var pierce float64 = 0
			tankCfg := game.GetTankConfig(tankID)
			if tankCfg != nil {
				if school == "energy" {
					power = tankCfg.Combat.EnergyAtk
					pierce = tankCfg.Combat.EnergyPen
				} else {
					power = tankCfg.Combat.Attack
					pierce = tankCfg.Combat.Pierce
				}
				if power <= 0 {
					power = 100
				}
			}
			room.Battle.AddBullet(&game.BulletFlight{
				ID:         bulletID,
				OwnerID:    charID,
				Camp:       camp,
				Template:   ev.Template,
				StartX:     float64(ev.StartX),
				StartY:     float64(ev.StartY),
				DestX:      float64(destX),
				DestY:      float64(destY),
				Speed:      speedPPS,
				StartTime:  time.Now().UnixMilli(),
				LifeMS:     lifeMS,
				Power:      power,
				School:     school,
				Pierce:     pierce,
				DamageMult: ev.DamageMult,
				Basic:      slotNo == 0 || ev.Basic,
				HitsWall:   hitStatic,
				TargetID:   ev.TargetID,
			})
		}
	}
	if len(res.AreaHits) > 0 && room.Battle != nil {
		camp := c.roomMgr.GetMemberCamp(room.ID, charID)
		members := c.roomMgr.GetMembers(room.ID)
		positions := make(map[uint32]*game.MemberPos, len(members))
		for _, mid := range members {
			x, y := c.roomMgr.GetMemberPos(room.ID, mid)
			positions[mid] = &game.MemberPos{X: x, Y: y}
		}
		nowMS := time.Now().UnixMilli()
		if room.Battle != nil {
			if res.ImmuneMS > 0 {
				room.Battle.SetDamageImmune(charID, res.ImmuneMS, nowMS)
			}
			if res.DamageReduceMS > 0 && res.DamageReducePct > 0 {
				room.Battle.SetDamageReduce(charID, res.DamageReducePct, res.DamageReduceMS, nowMS)
			}
			if len(res.Shields) > 0 {
				var shieldChanges []struct {
					ObjID  uint32
					Shield int32
				}
				for _, sh := range res.Shields {
					if newShield, ok := room.Battle.AddShield(sh.TargetID, sh.Amount, sh.MaxHPPct); ok {
						shieldChanges = append(shieldChanges, struct {
							ObjID  uint32
							Shield int32
						}{sh.TargetID, newShield})
					}
				}
				if len(shieldChanges) > 0 {
					c.broadcast.SendToAll(room.Members, 0, protocol.EncodeSyncSceneCombatEx(nil, nil, nil, nil, shieldChanges))
				}
			}
			for _, cp := range res.CooldownPcts {
				if cd, ok := room.Battle.ScaleSlotCooldown(charID, cp.SlotNo, cp.SkillID, cp.Factor, nowMS); ok {
					cdFrame := protocol.EncodeNotifySkillCooldown(charID, cd.SkillID, cd.SlotNo, uint64(nowMS+int64(cd.CooldownMS)))
					c.broadcast.SendToAll(room.Members, 0, cdFrame)
				}
			}
		}
		for _, area := range res.AreaHits {
			tickRes, hitPlayers := room.Battle.ApplyAreaHit(charID, camp, area, positions, nowMS)
			c.broadcastTickResult(room, room.Battle, members, tickRes)
			for _, targetID := range hitPlayers {
				for _, buffTpl := range area.OnHitBuffs {
					applied, dur, stacks := room.Battle.ApplyBuff(game.BuffEvent{TargetID: targetID, TemplateID: buffTpl, InstID: buffTpl}, charID, nowMS)
					if applied {
						bf := protocol.EncodeNotifyAddBuff(targetID, buffTpl, buffTpl, stacks, charID, dur)
						c.broadcast.SendToAll(members, 0, bf)
					}
				}
			}
		}
	}
	for _, sk := range res.Skills {
		skillFrame := protocol.EncodeSyncSceneSkill(charID, sk.TargetID, sk.Template, sk.StartX, sk.StartY, sk.DestX, sk.DestY, sk.Ready)
		c.broadcast.SendToAll(room.Members, 0, skillFrame)
		log.Printf("[%s] player %d (tank=%d) cast skill %d (slot=%d, target=%d, ready=%d) from (%d,%d) to (%d,%d)", c.role, charID, tankID, sk.Template, slotNo, sk.TargetID, sk.Ready, sk.StartX, sk.StartY, sk.DestX, sk.DestY)
	}
	for _, mv := range res.Moves {
		if mv.Speed > 0 {
			c.roomMgr.SetMemberPos(room.ID, charID, mv.DestX, mv.DestY)
		}
		moveFrame := protocol.EncodeSyncSceneMove(charID, mv.DestX, mv.DestY, mv.Speed, 0, mv.MoveType)
		c.broadcast.SendToAll(room.Members, 0, moveFrame)
	}
	for _, bf := range res.Buffs {
		if bf.Remove {
			if room.Battle != nil {
				room.Battle.ApplyBuff(bf, charID, time.Now().UnixMilli())
			}
			c.broadcast.SendToAll(room.Members, 0, protocol.EncodeNotifyRemoveBuff(bf.TargetID, bf.InstID))
			continue
		}
		dur := bf.DurationMS
		stacks := bf.Stacks
		if room.Battle != nil {
			var applied bool
			applied, dur, stacks = room.Battle.ApplyBuff(bf, charID, time.Now().UnixMilli())
			if !applied {
				continue
			}
		}
		if stacks == 0 {
			stacks = 1
		}
		c.broadcast.SendToAll(room.Members, 0, protocol.EncodeNotifyAddBuff(bf.TargetID, bf.TemplateID, bf.InstID, stacks, charID, dur))
	}
	nowMS := time.Now().UnixMilli()
	if room.Battle != nil {
		if res.ImmuneMS > 0 {
			room.Battle.SetDamageImmune(charID, res.ImmuneMS, nowMS)
		}
		if res.DamageReduceMS > 0 && res.DamageReducePct > 0 {
			room.Battle.SetDamageReduce(charID, res.DamageReducePct, res.DamageReduceMS, nowMS)
		}
		if len(res.Shields) > 0 {
			var shieldChanges []struct {
				ObjID  uint32
				Shield int32
			}
			for _, sh := range res.Shields {
				if newShield, ok := room.Battle.AddShield(sh.TargetID, sh.Amount, sh.MaxHPPct); ok {
					shieldChanges = append(shieldChanges, struct {
						ObjID  uint32
						Shield int32
					}{sh.TargetID, newShield})
				}
			}
			if len(shieldChanges) > 0 {
				c.broadcast.SendToAll(room.Members, 0, protocol.EncodeSyncSceneCombatEx(nil, nil, nil, nil, shieldChanges))
			}
		}
		for _, cp := range res.CooldownPcts {
			if cd, ok := room.Battle.ScaleSlotCooldown(charID, cp.SlotNo, cp.SkillID, cp.Factor, nowMS); ok {
				cdFrame := protocol.EncodeNotifySkillCooldown(charID, cd.SkillID, cd.SlotNo, uint64(nowMS+int64(cd.CooldownMS)))
				c.broadcast.SendToAll(room.Members, 0, cdFrame)
			}
		}
	}
	for _, sw := range res.SlotSwaps {
		var endMS uint64
		if sw.CooldownMS > 0 {
			endMS = uint64(nowMS + int64(sw.CooldownMS))
		}
		swapFrame := protocol.EncodeNotifySwapSkill(sw.SkillID, sw.SlotNo, endMS)
		c.broadcast.SendTo(charID, swapFrame)
	}
	for _, cd := range res.Cooldowns {
		if room.Battle != nil {
			room.Battle.SetSlotCooldown(charID, cd.SlotNo, cd.CooldownMS, nowMS)
		}
		cdFrame := protocol.EncodeNotifySkillCooldown(charID, cd.SkillID, cd.SlotNo, uint64(nowMS+int64(cd.CooldownMS)))
		c.broadcast.SendToAll(room.Members, 0, cdFrame)
	}
	for _, obj := range res.Objects {
		if obj.Remove {
			continue // TODO: send via 1564 expired_bullets vector
		}
		objID := c.roomMgr.NextObjectID(room.ID)
		objFrame := protocol.EncodeAddObject(0, objID, obj.Template, obj.PosX, obj.PosY, obj.Camp, obj.OwnerID)
		c.broadcast.SendToAll(room.Members, 0, objFrame)
		log.Printf("[%s] player %d added object %d (template=%d) at (%d,%d) life=%dms", c.role, charID, objID, obj.Template, obj.PosX, obj.PosY, obj.LifeMS)
		if obj.LifeMS > 0 {
			expireID := objID
			time.AfterFunc(time.Duration(obj.LifeMS)*time.Millisecond, func() {
				r := c.roomMgr.GetRoom(room.ID)
				if r == nil {
					return
				}
				// Remove expired object via 1564 expired_bullets vector
				expFrame := protocol.EncodeSyncSceneExpiredBullet(expireID)
				c.broadcast.SendToAll(r.Members, 0, expFrame)
			})
		}
	}
	for _, d := range res.Delayed {
		if d.Run == nil {
			continue
		}
		delay := time.Duration(d.DelayMS) * time.Millisecond
		fn := d.Run
		time.AfterFunc(delay, func() {
			r := c.roomMgr.GetRoom(room.ID)
			if r == nil {
				return
			}
			if r.Battle != nil && (!r.Battle.IsAlive(charID) || r.Battle.IsFinished()) {
				return
			}
			if r.Battle != nil {
				r.Battle.BehaviorMu.Lock()
			}
			delayedRes := fn()
			if r.Battle != nil {
				r.Battle.BehaviorMu.Unlock()
			}
			c.dispatchActionResult(r, charID, tankID, slotNo, delayedRes)
		})
	}
}

// handleVersion handles message 52 → responds with 903

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

		tankCfg := game.GetTankConfig(activeTankID)
		tankSkills := tankCfg.SkillArray()
		c.roomMgr.SetMemberTank(room.ID, mid, activeTankID)
		c.roomMgr.SetMemberSkills(room.ID, mid, tankSkills)
		beh := c.roomMgr.InitMemberBehavior(room.ID, mid, activeTankID)

		camp := c.roomMgr.GetMemberCamp(room.ID, mid)

		// Get spawn position from map config (like Python)
		spawnCfg := game.GetMapSpawnConfig(room.MapID)
		spawnPt := spawnCfg.Spawn(camp, idx)
		spawnX, spawnY := spawnPt.X, spawnPt.Y
		c.roomMgr.SetMemberPos(room.ID, mid, spawnX, spawnY)
		beh.OnSpawn(&game.ActorContext{
			RoomID:  room.ID,
			ActorID: mid,
			TankID:  activeTankID,
			Camp:    camp,
			PosX:    spawnX,
			PosY:    spawnY,
			Config:  tankCfg,
		})

		tInfo := &protocol.TankBattleInfo{
			ObjID:        mid, // ObjID matches account_oid so tanks.has(self_id) in Godot client succeeds
			AcctOid:      mid,
			X:            spawnX,
			Y:            spawnY,
			HP:           tankCfg.HP,
			MaxHP:        tankCfg.HP,
			Star:         1,
			Camp:         camp,
			Name:         name,
			LifeCount:    3,
			BattleExp:    0,
			BattleLevel:  1,
			TankLevel:    tankLvl,
			MP:           tankCfg.MP,
			MaxMP:        tankCfg.MP,
			Shield:       0,
			FireRate:     tankCfg.FireRateMS,
			MoveSpeed:    tankCfg.MoveSpeed,
			NormalBullet: tankCfg.NormalBullet.Template,
			Skills:       tankSkills,
		}
		tanks = append(tanks, tInfo)
	}

	now := uint32(time.Now().Unix())

	// Initialize battle state with HP + timer
	durMS, winTarget, modeType := game.GetMapBattleRule(room.MapID)
	battleState := game.NewBattleState(durMS)
	battleState.MapID = room.MapID
	battleState.ModeType = modeType
	battleState.WinTarget = winTarget
	for _, t := range tanks {
		camp := c.roomMgr.GetMemberCamp(room.ID, t.ObjID)
		battleState.AddMember(t.ObjID, t.HP, camp, 0, t.X, t.Y)
	}
	// Set tankID and spawnIndex for each member in battle state
	campIndices := map[uint8]int{} // track per-camp index for spawn assignment
	for _, mid := range members {
		tankID := c.roomMgr.GetMemberTank(room.ID, mid)
		camp := c.roomMgr.GetMemberCamp(room.ID, mid)
		if s := battleState.GetMemberState(mid); s != nil {
			s.TankID = tankID
			s.SpawnIndex = campIndices[camp]
		}
		if tCfg := game.GetTankConfig(tankID); tCfg != nil && tCfg.MP > 0 {
			battleState.SetMemberMP(mid, tCfg.MP, tCfg.MP, 5, 1000)
		}
		campIndices[camp]++
	}

	// Load destructible map objects (NPCs), capture flags & solid walls
	if c.roomMgr.StaticDir != "" {
		battleState.NPCs = game.LoadMapNPCs(c.roomMgr.StaticDir, room.MapID)
		battleState.Flags = game.LoadMapFlags(c.roomMgr.StaticDir, room.MapID)
		mw := game.LoadMapWalls(c.roomMgr.StaticDir, room.MapID)
		battleState.Walls = mw.BulletWalls       // solid only — for bullet collision
		battleState.MoveWalls = mw.MovementWalls // solid + water — for tank movement
		battleState.AirDrops = game.LoadMapAirDrops(c.roomMgr.StaticDir, room.MapID)
	}

	room.Battle = battleState

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

	// Start battle tick loop
	go c.battleTickLoop(room)
}

// battleTickLoop runs the game loop at 50ms intervals, processing bullet collisions, HP, deaths, and timer.
func (c *WSConn) battleTickLoop(room *game.Room) {
	bs := room.Battle
	if bs == nil {
		return
	}
	ticker := time.NewTicker(game.TickIntervalMS * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-bs.StopCh():
			return
		case <-ticker.C:
			c.processTick(room)
		}
	}
}

// processTick processes one game tick.
func (c *WSConn) processTick(room *game.Room) {
	bs := room.Battle
	if bs == nil {
		return
	}

	// Check if battle was force-ended (e.g. forfeit) — send settlement and stop
	if bs.IsFinished() {
		c.sendSettlement(room, bs)
		bs.Stop()
		return
	}

	// Gather positions
	members := c.roomMgr.GetMembers(room.ID)
	positions := make(map[uint32]*game.MemberPos)
	for _, mid := range members {
		x, y := c.roomMgr.GetMemberPos(room.ID, mid)
		positions[mid] = &game.MemberPos{X: x, Y: y}
	}

	// Run tick
	result := bs.Tick(positions)
	c.broadcastTickResult(room, bs, members, result)
}

// broadcastTickResult broadcasts HP/shield/delta/death/respawn/score events and handles game over.
func (c *WSConn) broadcastTickResult(room *game.Room, bs *game.BattleState, members []uint32, result game.TickResult) {
	if len(result.HpChanges) > 0 || len(result.Deaths) > 0 || len(result.BlownBullets) > 0 || len(result.ExpiredIDs) > 0 || len(result.Respawns) > 0 || len(result.NPCDamages) > 0 || len(result.ShieldChanges) > 0 {
		// Build combined 1564 packet
		hpEntries := make([]struct {
			ObjID uint32
			HP    int32
		}, len(result.HpChanges))
		for i, hp := range result.HpChanges {
			hpEntries[i] = struct {
				ObjID uint32
				HP    int32
			}{hp.ObjID, hp.HP}
		}
		deathEntries := make([]struct {
			ObjID uint32
			X, Y  int16
		}, 0, len(result.Deaths)+len(result.NPCDamages))
		for _, d := range result.Deaths {
			deathEntries = append(deathEntries, struct {
				ObjID uint32
				X, Y  int16
			}{d.VictimID, d.X, d.Y})
		}
		// Add destroyed NPC deaths
		for _, nd := range result.NPCDamages {
			if nd.Dead {
				deathEntries = append(deathEntries, struct {
					ObjID uint32
					X, Y  int16
				}{nd.NpcID, nd.X, nd.Y})
			}
		}
		blownIDs := make([]uint32, len(result.BlownBullets))
		for i, b := range result.BlownBullets {
			blownIDs[i] = b.BulletID
		}
		shieldEntries := make([]struct {
			ObjID  uint32
			Shield int32
		}, len(result.ShieldChanges))
		for i, s := range result.ShieldChanges {
			shieldEntries[i] = struct {
				ObjID  uint32
				Shield int32
			}{s.ObjID, s.Shield}
		}

		combatFrame := protocol.EncodeSyncSceneCombatEx(hpEntries, deathEntries, blownIDs, result.ExpiredIDs, shieldEntries)
		c.broadcast.SendToAll(members, 0, combatFrame)

		// Send damage/heal fly text (msg 1605)
		if len(result.HpDeltas) > 0 {
			deltas := make([]protocol.HpDelta, len(result.HpDeltas))
			for i, d := range result.HpDeltas {
				var fury uint8
				if d.Crit && d.Delta < 0 {
					fury = 1
				}
				deltas[i] = protocol.HpDelta{
					ObjID:    d.ObjID,
					Delta:    d.Delta,
					Fury:     fury,
					CasterID: d.CasterID,
				}
			}
			hpChangeFrame := protocol.EncodeSyncHpChange(deltas)
			c.broadcast.SendToAll(members, 0, hpChangeFrame)
		}

		// Send kill notifications + respawn timers
		for _, death := range result.Deaths {
			killFrame := protocol.EncodeNotifyKillInfo(death.KillerID, death.VictimID, death.SkillTpl, death.X, death.Y)
			c.broadcast.SendToAll(members, 0, killFrame)

			elapsed := bs.GetElapsedMS()
			respawnDelay := game.RespawnDelay(elapsed)
			respawnFrame := protocol.EncodeNotifyRespawnTimer(death.VictimID, int32(respawnDelay))
			c.broadcast.SendToAll(members, 0, respawnFrame)

			log.Printf("[battle] 💀 player %d killed by %d (skill=%d, respawn=%dms)", death.VictimID, death.KillerID, death.SkillTpl, respawnDelay)
		}

		// Send score update after kills (msg 1710)
		if len(result.Deaths) > 0 {
			scores := bs.GetScores()
			scoreFrame := protocol.EncodeNotifyCampKillNum(scores[1], scores[2])
			c.broadcast.SendToAll(members, 0, scoreFrame)
		}

		// Send respawn/born notifications
		for _, resp := range result.Respawns {
			// Build full TankBattleInfo for 1552 (client expects m_selfData = TankInfo)
			state := bs.GetMemberState(resp.CharID)
			tankID := c.roomMgr.GetMemberTank(room.ID, resp.CharID)
			camp := c.roomMgr.GetMemberCamp(room.ID, resp.CharID)
			char := c.store.GetCharacter(resp.CharID)
			name := fmt.Sprintf("Player_%d", resp.CharID)
			var tankLvl uint8 = 1
			if char != nil {
				name = char.Name
				for i := range char.Tanks {
					if char.Tanks[i].ExtFlag&2 != 0 {
						tankLvl = char.Tanks[i].TankLevel
						break
					}
				}
			}
			tankCfg := game.GetTankConfig(tankID)
			hp := state.MaxHP
			if state != nil {
				hp = state.HP
			}
			bornTank := &protocol.TankBattleInfo{
				ObjID:       resp.CharID,
				AcctOid:     resp.CharID,
				X:           resp.X,
				Y:           resp.Y,
				HP:          hp,
				MaxHP:       state.MaxHP,
				Star:        1,
				Camp:        camp,
				Name:        name,
				LifeCount:   3,
				BattleExp:   0,
				BattleLevel: 1,
				TankLevel:   tankLvl,
				MP:          tankCfg.MP,
				MaxMP:       tankCfg.MP,
				Shield:      0,
			}
			bornFrame := protocol.EncodeNotifyBorn(bornTank)
			c.broadcast.SendToAll(members, 0, bornFrame)
			c.roomMgr.SetMemberPos(room.ID, resp.CharID, resp.X, resp.Y)
			log.Printf("[battle] 🔄 player %d respawned at (%d,%d)", resp.CharID, resp.X, resp.Y)
		}
	}

	// Send occupy flag snapshot (1565) & flag score ticks (1732)
	if len(result.FlagSnapshot) > 0 {
		wires := make([]protocol.OccupyFlagWire, len(result.FlagSnapshot))
		for i, f := range result.FlagSnapshot {
			wires[i] = protocol.OccupyFlagWire{
				Index:    f.Index,
				Camp:     f.Camp,
				Locked:   f.Locked,
				Progress: f.Progress,
			}
		}
		c.broadcast.SendToAll(members, 0, protocol.EncodeNotifyOccupyState(wires))
	}
	for _, fs := range result.FlagScores {
		c.broadcast.SendToAll(members, 0, protocol.EncodeNotifyOccupyScore(fs.Index, fs.Camp, fs.Gain))
	}
	for _, bf := range result.Buffs {
		var frame []byte
		if bf.Remove {
			frame = protocol.EncodeNotifyRemoveBuff(bf.TargetID, bf.InstID)
		} else {
			frame = protocol.EncodeNotifyAddBuff(bf.TargetID, bf.TemplateID, bf.InstID, bf.Stacks, bf.TargetID, bf.DurationMS)
		}
		c.broadcast.SendToAll(members, 0, frame)
	}
	for _, ac := range result.AttrChanges {
		c.broadcast.SendToAll(members, 0, protocol.EncodeNotifyAttrChange(ac.CharID, ac.UpdateType, ac.Value))
	}
	if len(result.MpChanges) > 0 {
		mpWires := make([]struct {
			ObjID uint32
			MP    int32
		}, len(result.MpChanges))
		for i, mc := range result.MpChanges {
			mpWires[i].ObjID = mc.ObjID
			mpWires[i].MP = mc.MP
		}
		c.broadcast.SendToAll(members, 0, protocol.EncodeSyncSceneMP(mpWires))
	}
	for _, ad := range result.AddDrops {
		c.broadcast.SendToAll(members, 0, protocol.EncodeAddDrop(room.ID, ad.DropID, ad.TemplateID, ad.X, ad.Y))
	}
	if len(result.RemovedObjects) > 0 {
		c.broadcast.SendToAll(members, 0, protocol.EncodeSyncSceneDel(result.RemovedObjects))
	}
	for _, tf := range result.TurretFires {
		c.broadcast.SendToAll(members, 0, protocol.EncodeSyncSceneFire(tf.BulletID, tf.ShooterID, tf.StartX, tf.StartY, tf.DestX, tf.DestY, tf.Speed, tf.Template))
	}
	for _, td := range result.TakeDamages {
		tankID := c.roomMgr.GetMemberTank(room.ID, td.TargetID)
		tx, ty := c.roomMgr.GetMemberPos(room.ID, td.TargetID)
		beh := c.roomMgr.GetMemberBehavior(room.ID, td.TargetID, tankID)
		ctx := &game.ActorContext{
			RoomID:  room.ID,
			ActorID: td.TargetID,
			TankID:  tankID,
			Camp:    c.roomMgr.GetMemberCamp(room.ID, td.TargetID),
			PosX:    tx,
			PosY:    ty,
			Config:  game.GetTankConfig(tankID),
		}
		bs.BehaviorMu.Lock()
		res := beh.OnTakeDamage(ctx, td.AttackerID, td.Damage, td.IsSkill)
		bs.BehaviorMu.Unlock()
		if len(res.Buffs) > 0 || len(res.Shields) > 0 || len(res.CooldownPcts) > 0 || len(res.AreaHits) > 0 || len(res.Fires) > 0 {
			c.dispatchActionResult(room, td.TargetID, tankID, 0, res)
		}
	}
	for _, bh := range result.BulletHits {
		tankID := c.roomMgr.GetMemberTank(room.ID, bh.AttackerID)
		ax, ay := c.roomMgr.GetMemberPos(room.ID, bh.AttackerID)
		beh := c.roomMgr.GetMemberBehavior(room.ID, bh.AttackerID, tankID)
		ctx := &game.ActorContext{
			RoomID:  room.ID,
			ActorID: bh.AttackerID,
			TankID:  tankID,
			Camp:    c.roomMgr.GetMemberCamp(room.ID, bh.AttackerID),
			PosX:    ax,
			PosY:    ay,
			TargetX: bh.TargetX,
			TargetY: bh.TargetY,
			Config:  game.GetTankConfig(tankID),
		}
		bs.BehaviorMu.Lock()
		res := beh.OnBulletHit(ctx, bh.Template, bh.TargetID)
		bs.BehaviorMu.Unlock()
		if len(res.Buffs) > 0 || len(res.AreaHits) > 0 || len(res.Fires) > 0 || len(res.Skills) > 0 {
			c.dispatchActionResult(room, bh.AttackerID, tankID, 0, res)
		}
	}

	// Handle game over
	if result.GameOver {
		c.sendSettlement(room, bs)
		bs.Stop()
	}
}

// sendSettlement builds and broadcasts the 1708 settlement packet.
// Uses MarkSettlementSent to prevent double-sending.
func (c *WSConn) sendSettlement(room *game.Room, bs *game.BattleState) {
	if !bs.MarkSettlementSent() {
		return // already sent
	}
	members := c.roomMgr.GetMembers(room.ID)
	winner := bs.GetWinner()
	scores := bs.GetScores()
	elapsed := int32(bs.GetElapsedMS())

	log.Printf("[battle] 🏆 game over! winner=camp%d scores=[%d,%d] elapsed=%dms", winner, scores[1], scores[2], elapsed)

	var players []protocol.SettlementPlayer
	// Also include battle states for members who might have left
	for _, mid := range members {
		state := bs.GetMemberState(mid)
		camp := c.roomMgr.GetMemberCamp(room.ID, mid)
		tankID := c.roomMgr.GetMemberTank(room.ID, mid)
		if state != nil {
			players = append(players, protocol.SettlementPlayer{
				AcctID:  mid,
				Kills:   state.Kills,
				Deaths:  state.Deaths,
				Assists: state.Assists,
				Damage:  state.DamageOut,
				Camp:    camp,
				TankID:  tankID,
			})
		}
	}

	settlementFrame := protocol.EncodeNotifySettlement(0, room.MapID, elapsed, room.Type, winner, 0, scores, players, protocol.HonorAwards{})
	c.broadcast.SendToAll(members, 0, settlementFrame)

	// === Post-battle quest progress update ===
	for _, sp := range players {
		var wins uint32
		if sp.Camp == winner && winner != 0 {
			wins = 1
		}
		updated := c.questMgr.UpdateBattleProgress(sp.AcctID,
			uint32(sp.Kills), uint32(sp.Damage), 1, wins)
		if len(updated) > 0 {
			for _, q := range updated {
				frame := protocol.EncodeNotifyQuestUpdate(protocol.QuestData{
					QuestID: q.QuestID, State: q.State, Count: q.Count,
					Field3: q.Field3, Field4: q.Field4, Field5: q.Field5, Field6: q.Field6,
				})
				c.broadcast.SendTo(sp.AcctID, frame)
			}
		}
	}
}
