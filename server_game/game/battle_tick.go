package game

import (
	"math"
	"math/rand"
	"sync"
	"time"
)

// ----- Battle State -----

// MemberState tracks a member's battle HP and status.
type MemberState struct {
	HP                int32
	MaxHP             int32
	MP                int32
	MaxMP             int32
	MPRecover         int32 // passive MP gained per MPRecInterv
	MPRecInterv       int32 // passive MP regen interval in ms (default 1000)
	NextMPRegenAt     int64 // unix ms for next passive MP regen
	Shield            int32 // current shield HP (absorbs damage before HP)
	Alive             bool
	Camp              uint8
	RespawnAt         int64 // unix ms, 0 = not respawning
	Kills             int32
	Deaths            int32
	Assists           int32
	DamageOut         int32 // total damage dealt
	DamageIn          int32 // total damage received
	TankID            uint32
	SpawnX            int16
	SpawnY            int16
	SpawnIndex        int                   // player index for spawn point selection
	RepairReadyAt     int64                 // unix ms cooldown before next HP box heal (15s)
	Cooldowns         map[uint8]int64       // slotNo -> unix ms when slot is ready again
	DamageImmuneUntil int64                 // unix ms until damage immunity expires
	DamageReduceUntil int64                 // unix ms until damage reduction expires
	DamageReducePct   float64               // e.g. 0.50
	ActiveBuffs       map[uint32]ActiveBuff // active buffs/debuffs by InstID
	LastSyncSpeed     int32                 // last synced move speed (msg 1560 type 1)
	LastSyncFireMS    int32                 // last synced fire interval ms (msg 1560 type 4)
	MapAmmoTemplate   uint32                // 105 (triple spread) or 106 (rapid burst), 0 = none
	MapAmmoRemaining  int                   // remaining basic attacks with map ammo
	MapShieldHits     int                   // remaining hits blocked by pickup 413 (buff 30101)
}

// BulletFlight tracks an in-flight projectile for collision detection.
type BulletFlight struct {
	ID         uint32
	OwnerID    uint32
	Camp       uint8
	Template   uint32
	StartX     float64
	StartY     float64
	DestX      float64
	DestY      float64
	Speed      float64 // pixels per second
	StartTime  int64   // unix ms
	LifeMS     int64   // max lifetime ms (from SkillTemplate iLifeTime or distance/speed)
	Power      float64 // ATK at fire time (snapshot)
	School     string  // "physical" or "energy"
	Pierce     float64 // attacker pierce stat at fire time (snapshot)
	DamageMult float64 // damage multiplier for this bullet (0 means 1.0)
	Basic      bool    // true = basic attack (eligible for crit)
	HitsWall   bool    // true = clipped endpoint is a wall (explode on expiry)
	TargetID   uint32  // non-zero = homing missile tracking this target
	Lifesteal  float64 // per-skill lifesteal fraction (0 = none; from crystal or skill param)
}

// BulletPos computes the bullet's current position based on elapsed time.
func (b *BulletFlight) BulletPos(nowMS int64) (float64, float64) {
	elapsed := float64(nowMS-b.StartTime) / 1000.0
	dx := b.DestX - b.StartX
	dy := b.DestY - b.StartY
	dist := math.Hypot(dx, dy)
	if dist == 0 {
		return b.StartX, b.StartY
	}
	traveled := b.Speed * elapsed
	if traveled >= dist {
		return b.DestX, b.DestY
	}
	ratio := traveled / dist
	return b.StartX + dx*ratio, b.StartY + dy*ratio
}

// IsExpired checks if bullet has exceeded its lifetime or reached destination.
func (b *BulletFlight) IsExpired(nowMS int64) bool {
	if nowMS-b.StartTime >= b.LifeMS {
		return true
	}
	// Check if reached destination
	elapsed := float64(nowMS-b.StartTime) / 1000.0
	dx := b.DestX - b.StartX
	dy := b.DestY - b.StartY
	dist := math.Hypot(dx, dy)
	if dist == 0 {
		return true
	}
	return b.Speed*elapsed >= dist
}

// ----- HP Change / Death events -----

// HpChangeEvent represents an HP change to broadcast via m_hpVec.
type HpChangeEvent struct {
	ObjID uint32
	HP    int32 // current HP (absolute, not delta)
}

// MpChangeEvent represents an MP change to broadcast via m_mpVec.
type MpChangeEvent struct {
	ObjID uint32
	MP    int32 // current MP
}

// HpDeltaEvent represents an HP delta for msg 1605 (SyncHpChange) fly text.
type HpDeltaEvent struct {
	ObjID    uint32
	Delta    int32  // negative = damage, positive = heal
	Crit     bool   // true if critical hit
	CasterID uint32 // who caused the change
}

// ShieldChangeEvent represents a shield update for m_shieldVec in 1564.
type ShieldChangeEvent struct {
	ObjID  uint32
	Shield int32 // current shield value (absolute)
}

// DeathEvent represents a death to broadcast via m_deadVec + 1566.
type DeathEvent struct {
	VictimID uint32
	KillerID uint32
	SkillTpl uint32
	X, Y     int16
}

// BlownBulletEvent represents a bullet that hit something (m_blowUpVec).
type BlownBulletEvent struct {
	BulletID uint32
}

// ----- Battle Tick -----

const (
	TickIntervalMS  = 50         // 50ms = 20 ticks/sec
	HitboxRadius    = 40.0       // collision radius in pixels
	DefaultDuration = 180 * 1000 // 3 minutes in ms
	WinKills        = 25         // first to 25 kills wins
)

// RespawnDelay calculates dynamic respawn delay based on elapsed time.
// Formula from Python: min(30000, 5000 * (1 + elapsed // 120000))
// Starts at 5s, +5s every 2 minutes, capped at 30s.
func RespawnDelay(elapsedMS int64) int64 {
	periods := elapsedMS / 120000 // 2-minute periods
	if periods < 0 {
		periods = 0
	}
	delay := int64(5000) * (1 + periods)
	if delay > 30000 {
		delay = 30000
	}
	return delay
}

// BattleState holds all runtime battle data for a room.
type BattleState struct {
	mu         sync.Mutex
	BehaviorMu sync.Mutex // serializes per-tank ActorBehavior calls across WS & DelayedAction goroutines

	StartTime      int64 // unix ms
	Deadline       int64 // unix ms
	Duration       int64 // ms
	Finished       bool
	SettlementSent bool   // prevent double settlement
	Winner         uint8  // 0=draw, 1=camp1, 2=camp2
	MapID          uint32 // for spawn point lookup
	ModeType       uint8  // 1=base, 2=occupy, 3=deathmatch, 4=death
	WinTarget      int32  // score/kill target to win immediately (defaults to WinKills)

	States       map[uint32]*MemberState
	Bullets      map[uint32]*BulletFlight
	Scores       [3]int32           // Scores[1]=camp1 kills/score, Scores[2]=camp2 kills/score
	NPCs         map[uint32]*MapNPC // destructible map objects
	Flags        []*MapFlag         // capture points for occupy maps (ModeType == 2)
	Walls        []WallRect         // solid wall blocks — bullets collide with these
	MoveWalls    []WallRect         // solid + water walls — tanks cannot move through these
	AirDrops     []AirDropPoint     // air-drop spawn positions (chunk tag 5)
	AirDropDueAt int64              // unix ms for next periodic air drop
	Drops        map[uint32]*MapDrop
	NextDropID   uint32
	NextBulletID uint32

	MapBounds ArenaBounds // playable area bounds for tank clamping

	// Surrender vote state
	Vote         *SurrenderVote
	VoteEndAt    int64 // unix ms when current vote expires
	VoteCooldown int64 // unix ms when next vote can start

	stopCh chan struct{}
}

// NewBattleState creates a fresh battle state.
func NewBattleState(durationMS int64) *BattleState {
	now := time.Now().UnixMilli()
	if durationMS <= 0 {
		durationMS = DefaultDuration
	}
	return &BattleState{
		StartTime: now,
		Deadline:  now + durationMS,
		Duration:  durationMS,
		WinTarget: WinKills,
		States:    make(map[uint32]*MemberState),
		Bullets:   make(map[uint32]*BulletFlight),
		stopCh:    make(chan struct{}),
	}
}

// AddMember registers a member in the battle.
func (bs *BattleState) AddMember(charID uint32, hp int32, camp uint8, tankID uint32, spawnX, spawnY int16) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	bs.States[charID] = &MemberState{
		HP:        hp,
		MaxHP:     hp,
		Alive:     true,
		Camp:      camp,
		TankID:    tankID,
		SpawnX:    spawnX,
		SpawnY:    spawnY,
		Cooldowns: make(map[uint8]int64),
	}
}

// SetMemberMP initializes a member's MP, MaxMP, and passive regen parameters.
func (bs *BattleState) SetMemberMP(charID uint32, mp, maxMP, recover, recInterv int32) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	if s, ok := bs.States[charID]; ok {
		s.MP = mp
		s.MaxMP = maxMP
		s.MPRecover = recover
		s.MPRecInterv = recInterv
		if recInterv > 0 {
			s.NextMPRegenAt = time.Now().UnixMilli() + int64(recInterv)
		}
	}
}

// HasEnoughMP returns true if the member has at least cost MP (always true when cost <= 0).
func (bs *BattleState) HasEnoughMP(charID uint32, cost int32) bool {
	if cost <= 0 {
		return true
	}
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok {
		return false
	}
	return s.MP >= cost
}

// ConsumeMP deducts cost MP if available and returns (newMP, changed).
func (bs *BattleState) ConsumeMP(charID uint32, cost int32) (int32, bool) {
	if cost <= 0 {
		return 0, false
	}
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok || s.MP < cost {
		return 0, false
	}
	s.MP -= cost
	return s.MP, true
}

// AddMP adjusts a member's MP by delta (clamped to [0, MaxMP]) and returns (newMP, changed).
func (bs *BattleState) AddMP(charID uint32, delta int32) (int32, bool) {
	if delta == 0 {
		return 0, false
	}
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok || s.MaxMP <= 0 {
		return 0, false
	}
	before := s.MP
	s.MP += delta
	if s.MP < 0 {
		s.MP = 0
	} else if s.MP > s.MaxMP {
		s.MP = s.MaxMP
	}
	return s.MP, s.MP != before
}

func normalizeCooldownSlot(slotNo uint8) uint8 {
	if slotNo == 3 {
		return 10
	}
	return slotNo
}

// IsSlotOnCooldown returns true if the given skill slot is still on cooldown.
func (bs *BattleState) IsSlotOnCooldown(charID uint32, slotNo uint8, nowMS int64) bool {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok || s.Cooldowns == nil {
		return false
	}
	return s.Cooldowns[normalizeCooldownSlot(slotNo)] > nowMS
}

// SetSlotCooldown records the server-side cooldown expiry for a skill slot.
func (bs *BattleState) SetSlotCooldown(charID uint32, slotNo uint8, cooldownMS uint32, nowMS int64) {
	if cooldownMS == 0 {
		return
	}
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok {
		return
	}
	if s.Cooldowns == nil {
		s.Cooldowns = make(map[uint8]int64)
	}
	s.Cooldowns[normalizeCooldownSlot(slotNo)] = nowMS + int64(cooldownMS)
}

// SetDamageImmune grants temporary damage immunity to charID.
func (bs *BattleState) SetDamageImmune(charID uint32, durationMS int64, nowMS int64) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	if s, ok := bs.States[charID]; ok {
		s.DamageImmuneUntil = nowMS + durationMS
	}
}

// SetDamageReduce grants temporary % damage reduction to charID.
func (bs *BattleState) SetDamageReduce(charID uint32, pct float64, durationMS int64, nowMS int64) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	if s, ok := bs.States[charID]; ok {
		s.DamageReducePct = pct
		s.DamageReduceUntil = nowMS + durationMS
	}
}

// AddShield adds shield HP to charID (by fixed amount or fraction of MaxHP) and returns the new shield total.
func (bs *BattleState) AddShield(charID uint32, amount int32, maxHPPct float64) (int32, bool) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok {
		return 0, false
	}
	add := amount
	if maxHPPct > 0 {
		add += int32(math.Round(float64(s.MaxHP) * maxHPPct))
	}
	if add <= 0 {
		return s.Shield, false
	}
	s.Shield += add
	return s.Shield, true
}

// ScaleSlotCooldown multiplies a slot's remaining cooldown by factor and returns the updated CooldownEvent.
func (bs *BattleState) ScaleSlotCooldown(charID uint32, slotNo uint8, skillID uint32, factor float64, nowMS int64) (CooldownEvent, bool) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	s, ok := bs.States[charID]
	if !ok || s.Cooldowns == nil {
		return CooldownEvent{}, false
	}
	norm := normalizeCooldownSlot(slotNo)
	exp, exists := s.Cooldowns[norm]
	if !exists || exp <= nowMS {
		return CooldownEvent{}, false
	}
	rem := int64(math.Round(float64(exp-nowMS) * factor))
	if rem < 0 {
		rem = 0
	}
	s.Cooldowns[norm] = nowMS + rem
	return CooldownEvent{SlotNo: slotNo, SkillID: skillID, CooldownMS: uint32(rem)}, true
}

// applyDefenseModifiers applies generic damage immunity, per-school immunity, 3-hit map shield, and % damage reduction.
// school parameter: "physical", "energy", "true", or "" for school-agnostic checks (DoT etc.).
func applyDefenseModifiers(state *MemberState, damage int32, now int64, school string) (int32, bool) {
	if now < state.DamageImmuneUntil {
		return 0, true // immune
	}
	// Per-school immunity from buff templates (Python: damage_immune())
	if school != "" && IsSchoolImmuneLocked(state, school, now) {
		return 0, true
	}
	if state.MapShieldHits > 0 {
		state.MapShieldHits--
		return 0, true // absorbed by map shield pickup (413 / buff 30101)
	}
	if now < state.DamageReduceUntil && state.DamageReducePct > 0 {
		damage = int32(math.Round(float64(damage) * (1.0 - state.DamageReducePct)))
		if damage < 1 {
			damage = 1
		}
	}
	return damage, false
}

// AddBullet registers a bullet for tracking.
func (bs *BattleState) AddBullet(bullet *BulletFlight) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	bs.Bullets[bullet.ID] = bullet
}

// Stop signals the tick loop to stop.
func (bs *BattleState) Stop() {
	select {
	case <-bs.stopCh:
	default:
		close(bs.stopCh)
	}
}

// ForceEnd forces the battle to end with a winner (e.g. forfeit).
func (bs *BattleState) ForceEnd(winner uint8) {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	if bs.Finished {
		return
	}
	bs.Finished = true
	bs.Winner = winner
}

// StopCh returns the stop channel for select.
func (bs *BattleState) StopCh() <-chan struct{} {
	return bs.stopCh
}

// RespawnEvent represents a member that just respawned.
type RespawnEvent struct {
	CharID uint32
	X      int16
	Y      int16
}

// NPCDamageEvent represents damage dealt to a map NPC.
type NPCDamageEvent struct {
	NpcID uint32
	HP    int32 // current HP after damage
	Dead  bool
	X     int16
	Y     int16
}

// FlagWireEvent holds a flag snapshot entry for msg 1565.
type FlagWireEvent struct {
	Index    int32
	Camp     int32
	Locked   int32
	Progress int32
}

// FlagScoreEvent holds a flag score tick for msg 1732.
type FlagScoreEvent struct {
	Index int32
	Camp  int32
	Gain  int32
}

// BulletHitEvent notifies behavior hooks when a projectile hits an enemy player.
type BulletHitEvent struct {
	AttackerID uint32
	TargetID   uint32
	Template   uint32
	TargetX    int16
	TargetY    int16
}

// TakeDamageEvent notifies a victim's behavior when they take damage.
type TakeDamageEvent struct {
	TargetID   uint32
	AttackerID uint32
	Damage     int32
	IsSkill    bool
}

// TickResult holds events from one tick to be broadcast.
type TickResult struct {
	HpChanges      []HpChangeEvent
	MpChanges      []MpChangeEvent     // for m_mpVec in 1564
	HpDeltas       []HpDeltaEvent      // for msg 1605 fly text
	ShieldChanges  []ShieldChangeEvent // for m_shieldVec in 1564
	Deaths         []DeathEvent
	BlownBullets   []BlownBulletEvent
	ExpiredIDs     []uint32 // bullet IDs that expired (missed)
	Respawns       []RespawnEvent
	NPCDamages     []NPCDamageEvent
	FlagSnapshot   []FlagWireEvent
	FlagScores     []FlagScoreEvent
	Buffs          []BuffEvent
	AttrChanges    []AttrChangeEvent // for msg 1560 speed/fire-interval sync
	AddDrops       []AddDropEvent    // for msg 1556 map drops
	RemovedObjects []uint32          // for msg 1564 m_delVec
	TurretFires    []TurretFireEvent // for msg 1564 m_fireVec
	BulletHits     []BulletHitEvent
	TakeDamages    []TakeDamageEvent
	GameOver       bool
	Winner         uint8
	Scores         [3]int32
	ElapsedMS      int32
}

// Tick processes one game tick: moves bullets, checks collisions, checks timer.
func (bs *BattleState) Tick(positions map[uint32]*MemberPos) TickResult {
	bs.mu.Lock()
	defer bs.mu.Unlock()

	var result TickResult
	now := time.Now().UnixMilli()

	if bs.Finished {
		return result
	}

	// --- Check match timer ---
	if now >= bs.Deadline {
		bs.Finished = true
		bs.Winner = bs.determineWinner()
		result.GameOver = true
		result.Winner = bs.Winner
		result.Scores = bs.Scores
		result.ElapsedMS = int32(bs.Duration)
		return result
	}

	// --- Process bullets ---
	var expiredIDs []uint32
	var hitBullets []uint32

	for bulletID, bullet := range bs.Bullets {
		expired := bullet.IsExpired(now)

		// Get previous and current bullet positions along this tick segment (check final segment even if expired)
		prevTime := now - TickIntervalMS
		if prevTime < bullet.StartTime {
			prevTime = bullet.StartTime
		}
		currTime := now
		if expired && bullet.StartTime+bullet.LifeMS < currTime {
			currTime = bullet.StartTime + bullet.LifeMS
		}
		pxPrev, pyPrev := bullet.BulletPos(prevTime)
		// Homing missile: steer toward target's live position each tick
		if bullet.TargetID != 0 {
			if ts := bs.States[bullet.TargetID]; ts != nil && ts.Alive {
				if tpos := positions[bullet.TargetID]; tpos != nil {
					bullet.StartX = pxPrev
					bullet.StartY = pyPrev
					bullet.StartTime = prevTime
					bullet.DestX = float64(tpos.X)
					bullet.DestY = float64(tpos.Y)
				}
			}
		}
		bx, by := bullet.BulletPos(currTime)

		// 1. Find earliest wall hit along segment
		wallHit, wallFrac := SegmentHitsWall(bs.Walls, pxPrev, pyPrev, bx, by)

		// 2. Find earliest enemy player hit along segment
		var hitPlayerID uint32
		playerFrac := 2.0
		for memberID, state := range bs.States {
			if !state.Alive || state.Camp == bullet.Camp || memberID == bullet.OwnerID {
				continue
			}
			pos := positions[memberID]
			if pos == nil {
				continue
			}
			if hit, frac := SegmentCircleContact(pxPrev, pyPrev, bx, by, float64(pos.X), float64(pos.Y), HitboxRadius); hit && frac < playerFrac {
				playerFrac = frac
				hitPlayerID = memberID
			}
		}

		// 3. Find earliest NPC hit along segment
		var npcHit *MapNPCHitResult
		npcFrac := 2.0
		if bs.NPCs != nil {
			npcHit, npcFrac = CheckBulletNPCCollisionSegment(bs.NPCs, pxPrev, pyPrev, bx, by, bullet.Camp)
		}

		// Determine what was hit FIRST along the segment
		if wallHit && wallFrac <= playerFrac && wallFrac <= npcFrac {
			result.BlownBullets = append(result.BlownBullets, BlownBulletEvent{
				BulletID: bulletID,
			})
			hitBullets = append(hitBullets, bulletID)
			continue
		}

		bulletHitPlayer := false
		if hitPlayerID != 0 && playerFrac <= npcFrac {
			memberID := hitPlayerID
			state := bs.States[memberID]
			pos := positions[memberID]
			if state != nil && pos != nil {
				// Projectile block/reflect check (Python: projectile_blocked())
				blocked, reflected := CheckProjectileBlockedLocked(state, bullet.Basic, now)
				if blocked {
					result.BlownBullets = append(result.BlownBullets, BlownBulletEvent{BulletID: bulletID})
					hitBullets = append(hitBullets, bulletID)
					expiredIDs = append(expiredIDs, bulletID)
					if reflected {
						// Create reflected bullet aimed back at the attacker
						if attackerPos := positions[bullet.OwnerID]; attackerPos != nil {
							bs.NextBulletID++
							refBullet := &BulletFlight{
								ID:         bs.NextBulletID,
								OwnerID:    memberID, // reflector becomes new owner
								Camp:       state.Camp,
								Template:   bullet.Template,
								StartX:     float64(pos.X),
								StartY:     float64(pos.Y),
								DestX:      float64(attackerPos.X),
								DestY:      float64(attackerPos.Y),
								Speed:      bullet.Speed,
								StartTime:  now,
								LifeMS:     bullet.LifeMS,
								Power:      bullet.Power,
								School:     bullet.School,
								Pierce:     bullet.Pierce,
								DamageMult: bullet.DamageMult,
								Basic:      bullet.Basic,
							}
							bs.Bullets[refBullet.ID] = refBullet
						}
					}
					continue
				}

				// HIT! Calculate damage
				damage, isCrit := bs.calculateDamageEx(bullet, memberID, now)
				var immune bool
				damage, immune = applyDefenseModifiers(state, damage, now, bullet.School)
				if immune {
					result.BlownBullets = append(result.BlownBullets, BlownBulletEvent{BulletID: bulletID})
					hitBullets = append(hitBullets, bulletID)
					continue
				}
				result.TakeDamages = append(result.TakeDamages, TakeDamageEvent{
					TargetID:   memberID,
					AttackerID: bullet.OwnerID,
					Damage:     damage,
					IsSkill:    !bullet.Basic,
				})
				hpBefore := state.HP

				// Shield absorption: damage hits shield first
				shieldAbsorbed := int32(0)
				if state.Shield > 0 {
					if state.Shield >= damage {
						state.Shield -= damage
						shieldAbsorbed = damage
						damage = 0
					} else {
						shieldAbsorbed = state.Shield
						damage -= state.Shield
						state.Shield = 0
					}
					result.ShieldChanges = append(result.ShieldChanges, ShieldChangeEvent{
						ObjID:  memberID,
						Shield: state.Shield,
					})
				}

				state.HP -= damage
				if state.HP < 0 {
					state.HP = 0
				}

				// Track damage for the attacker
				totalDmg := shieldAbsorbed + damage
				hpLoss := hpBefore - state.HP
				if attacker, ok := bs.States[bullet.OwnerID]; ok {
					attacker.DamageOut += totalDmg
					// Lifesteal: heal attacker based on actual HP loss (not shield, not overkill)
					if bullet.Lifesteal > 0 && hpLoss > 0 && attacker.Alive {
						vampHeal := LifestealAmount(hpLoss, bullet.Lifesteal)
						if vampHeal > 0 {
							atkHPBefore := attacker.HP
							attacker.HP += vampHeal
							if attacker.HP > attacker.MaxHP {
								attacker.HP = attacker.MaxHP
							}
							actualVamp := attacker.HP - atkHPBefore
							if actualVamp > 0 {
								result.HpChanges = append(result.HpChanges, HpChangeEvent{ObjID: bullet.OwnerID, HP: attacker.HP})
								result.HpDeltas = append(result.HpDeltas, HpDeltaEvent{ObjID: bullet.OwnerID, Delta: actualVamp, CasterID: bullet.OwnerID})
							}
						}
					}
				}

				result.HpChanges = append(result.HpChanges, HpChangeEvent{
					ObjID: memberID,
					HP:    state.HP,
				})
				// HP delta for fly text (msg 1605)
				hpDelta := state.HP - hpBefore
				if hpDelta != 0 || shieldAbsorbed > 0 {
					delta := hpDelta
					if shieldAbsorbed > 0 && delta == 0 {
						delta = -shieldAbsorbed // show shield damage as negative delta
					}
					result.HpDeltas = append(result.HpDeltas, HpDeltaEvent{
						ObjID:    memberID,
						Delta:    delta,
						Crit:     isCrit,
						CasterID: bullet.OwnerID,
					})
				}
				result.BlownBullets = append(result.BlownBullets, BlownBulletEvent{
					BulletID: bulletID,
				})
				result.BulletHits = append(result.BulletHits, BulletHitEvent{
					AttackerID: bullet.OwnerID,
					TargetID:   memberID,
					Template:   bullet.Template,
					TargetX:    pos.X,
					TargetY:    pos.Y,
				})

				// Check death
				if state.HP <= 0 {
					state.Alive = false
					state.Deaths++
					elapsed := now - bs.StartTime
					state.RespawnAt = now + RespawnDelay(elapsed)
					ClearBuffsOnDeathLocked(state, memberID, &result)
					if pos != nil {
						bs.SpawnDropAtLocked(pos.X, pos.Y, 0.30, &result)
					}

					var killerCamp uint8
					if attacker, ok := bs.States[bullet.OwnerID]; ok {
						attacker.Kills++
						killerCamp = attacker.Camp
					}
					if killerCamp > 0 && killerCamp <= 2 && bs.ModeType != 1 && bs.ModeType != 2 {
						bs.Scores[killerCamp]++
					}

					px, py := int16(0), int16(0)
					if pos != nil {
						px, py = pos.X, pos.Y
					}
					result.Deaths = append(result.Deaths, DeathEvent{
						VictimID: memberID,
						KillerID: bullet.OwnerID,
						SkillTpl: bullet.Template,
						X:        px,
						Y:        py,
					})

					// Check win condition (first camp to reach WinTarget wins in score/deathmatch modes)
					winTarget := bs.WinTarget
					if winTarget <= 0 {
						winTarget = WinKills
					}
					if killerCamp > 0 && bs.ModeType != 1 && bs.ModeType != 2 && bs.Scores[killerCamp] >= winTarget {
						bs.Finished = true
						bs.Winner = killerCamp
						result.GameOver = true
						result.Winner = killerCamp
						result.Scores = bs.Scores
						result.ElapsedMS = int32(now - bs.StartTime)
					}
				}

				hitBullets = append(hitBullets, bulletID)
				bulletHitPlayer = true
			}
		}

		// If bullet didn't hit a player, apply NPC hit (already segment-checked above)
		if !bulletHitPlayer && npcHit != nil {
			npc := bs.NPCs[npcHit.NpcID]
			if npc != nil {
				var damage int32
				if npc.Type == 3 || npc.Type == 4 || npc.Type == 6 {
					// Base (3), Turret (4), or Repair Box (6): real attack damage
					mult := bullet.DamageMult
					if mult <= 0 {
						mult = 1.0
					}
					damage = int32(bullet.Power * mult)
				} else {
					// Ordinary destructible obstacle: max_hp / 4 per hit
					damage = npc.MaxHP / 4
				}
				if damage < 1 {
					damage = 1
				}
				npc.HP -= damage
				if npc.HP <= 0 {
					npc.HP = 0
					npc.Alive = false
				}
				result.HpChanges = append(result.HpChanges, HpChangeEvent{
					ObjID: npc.ID,
					HP:    npc.HP,
				})
				result.BlownBullets = append(result.BlownBullets, BlownBulletEvent{
					BulletID: bulletID,
				})
				if !npc.Alive {
					if npc.Type == 1 {
						bs.SpawnDropAtLocked(npc.X, npc.Y, 0.30, &result)
					}
					if npc.Type == 6 && npc.RepairTarget != 0 {
						result.Buffs = append(result.Buffs, BuffEvent{
							Remove: true, TargetID: npc.RepairTarget, InstID: 10,
						})
						npc.RepairTarget = 0
						npc.RepairTicksLeft = 0
					}
					result.NPCDamages = append(result.NPCDamages, NPCDamageEvent{
						NpcID: npc.ID,
						HP:    0,
						Dead:  true,
						X:     npc.X,
						Y:     npc.Y,
					})
					// Base destroyed -> opposing camp wins immediately
					if npc.Type == 3 && (npc.Camp == 1 || npc.Camp == 2) {
						winner := uint8(3 - npc.Camp)
						bs.Finished = true
						bs.Winner = winner
						result.GameOver = true
						result.Winner = winner
						result.Scores = bs.Scores
						result.ElapsedMS = int32(now - bs.StartTime)
					}
				}
				hitBullets = append(hitBullets, bulletID)
			}
		} else if !bulletHitPlayer && expired {
			if bullet.HitsWall {
				result.BlownBullets = append(result.BlownBullets, BlownBulletEvent{
					BulletID: bulletID,
				})
				hitBullets = append(hitBullets, bulletID)
			} else {
				expiredIDs = append(expiredIDs, bulletID)
			}
		}
	}

	// Remove hit bullets
	for _, id := range hitBullets {
		delete(bs.Bullets, id)
	}
	// Remove expired bullets
	for _, id := range expiredIDs {
		delete(bs.Bullets, id)
	}
	result.ExpiredIDs = expiredIDs

	// --- Check respawns ---
	spawnCfg := GetMapSpawnConfig(bs.MapID)
	for memberID, state := range bs.States {
		if !state.Alive && state.RespawnAt > 0 && now >= state.RespawnAt {
			state.HP = state.MaxHP
			state.Alive = true
			state.RespawnAt = 0
			// Use map-specific respawn point
			rpt := spawnCfg.Respawn(state.Camp, state.SpawnIndex)
			state.SpawnX = rpt.X
			state.SpawnY = rpt.Y
			result.HpChanges = append(result.HpChanges, HpChangeEvent{
				ObjID: memberID,
				HP:    state.HP,
			})
			result.HpDeltas = append(result.HpDeltas, HpDeltaEvent{
				ObjID:    memberID,
				Delta:    state.MaxHP,
				CasterID: memberID,
			})
			if state.MaxMP > 0 && state.MP != state.MaxMP {
				state.MP = state.MaxMP
				result.MpChanges = append(result.MpChanges, MpChangeEvent{
					ObjID: memberID,
					MP:    state.MP,
				})
			}
			result.Respawns = append(result.Respawns, RespawnEvent{
				CharID: memberID,
				X:      rpt.X,
				Y:      rpt.Y,
			})
		}
	}

	// --- Occupy / capture flag tick (ModeType == 2) ---
	if len(bs.Flags) > 0 && !bs.Finished {
		bs.tickFlags(positions, now, &result)
	}

	// --- HP Repair Box (iType == 6) & Turret AI (iType == 4) ---
	if bs.NPCs != nil && !bs.Finished {
		bs.tickRepairBoxes(positions, now, &result)
		bs.tickTurrets(positions, now, &result)
	}

	// --- Map Drops / Air-Drops & Map Shield cleanup ---
	if !bs.Finished {
		for memberID, state := range bs.States {
			if state.MapShieldHits <= 0 && state.ActiveBuffs != nil {
				if _, has := state.ActiveBuffs[30101]; has {
					bs.removeDropBuffLocked(memberID, 30101, &result)
				}
			}
		}
		bs.tickDrops(positions, now, &result)
	}

	// --- Buff expiration tick ---
	if !bs.Finished {
		bs.tickBuffs(now, &result)
	}

	return result
}

// calculateDamageEx computes damage from a bullet hit on a target, returning (damage, isCrit).
func (bs *BattleState) calculateDamageEx(bullet *BulletFlight, targetID uint32, now int64) (int32, bool) {
	raw := bullet.Power
	if raw <= 0 {
		raw = 50 // fallback minimum damage
	}

	// Apply attacker ATK buffs/debuffs
	pierce := bullet.Pierce
	if attacker, ok := bs.States[bullet.OwnerID]; ok {
		atkParam := AttrPhysAtk
		pierceParam := AttrPhysPierce
		if bullet.School == "energy" {
			atkParam = AttrEnergyAtk
			pierceParam = AttrEnergyPierce
		}
		raw = raw*(1+AttrBonusLocked(attacker, now, AttrAllAtk, atkParam)) + AttrFlatBonusLocked(attacker, now, AttrAllAtk, atkParam)
		pierce = pierce*(1+AttrBonusLocked(attacker, now, AttrAllPierce, pierceParam)) + AttrFlatBonusLocked(attacker, now, AttrAllPierce, pierceParam)
	}

	// Apply skill damage multiplier
	mult := bullet.DamageMult
	if mult <= 0 {
		mult = 1.0
	}
	raw *= mult

	// Look up target's armor and active buff/debuff modifiers
	var targetArmor, defBonusPct, defBonusFlat, incomingBonus float64
	var reductions []float64
	if target, ok := bs.States[targetID]; ok {
		armorParam := AttrPhysArmor
		if bullet.School == "energy" {
			armorParam = AttrEnergyArmor
		}
		if cfg := GetTankConfig(target.TankID); cfg != nil {
			if bullet.School == "energy" {
				targetArmor = cfg.Combat.EnergyDef
			} else {
				targetArmor = cfg.Combat.Armor
			}
		}
		defBonusPct = AttrBonusLocked(target, now, AttrAllArmor, armorParam)
		defBonusFlat = AttrFlatBonusLocked(target, now, AttrAllArmor, armorParam)
		reductions, incomingBonus = DamageModifiersLocked(target, bullet.Basic, now)
	}

	const baseCritChance = 0.15
	isCrit := bullet.Basic && bullet.School != "true" && rand.Float64() < baseCritChance

	dmg := CalculateDamage(DamageParams{
		Raw:           raw,
		School:        bullet.School,
		Pierce:        pierce,
		TargetArmor:   targetArmor,
		DefBonusPct:   defBonusPct,
		DefBonusFlat:  defBonusFlat,
		IncomingBonus: incomingBonus,
		Reductions:    reductions,
		Critical:      isCrit,
	})
	if dmg < 1 {
		dmg = 1 // minimum 1 damage
	}
	return int32(dmg), isCrit
}

// ApplyAreaHit evaluates an immediate cone, circle, or rectangle AOE hit against all enemy actors and NPCs.
// Returns a TickResult with HP/shield/delta/death events and the list of hit player IDs (for buff application).
func (bs *BattleState) determineWinner() uint8 {
	if bs.ModeType == 1 && bs.NPCs != nil {
		var hpPct [3]float64
		for _, npc := range bs.NPCs {
			if npc.Type == 3 && (npc.Camp == 1 || npc.Camp == 2) && npc.MaxHP > 0 {
				hpPct[npc.Camp] = float64(npc.HP) / float64(npc.MaxHP)
			}
		}
		if hpPct[1] > hpPct[2] {
			return 1
		}
		if hpPct[2] > hpPct[1] {
			return 2
		}
	} else {
		s1, s2 := bs.Scores[1], bs.Scores[2]
		if s1 > s2 {
			return 1
		}
		if s2 > s1 {
			return 2
		}
	}

	// Tie: side with fewer deaths wins ("chọn bên tỉ số ít hơn thắng")
	var deaths [3]int32
	for _, state := range bs.States {
		if state.Camp == 1 || state.Camp == 2 {
			deaths[state.Camp] += state.Deaths
		}
	}
	if deaths[1] < deaths[2] {
		return 1
	}
	if deaths[2] < deaths[1] {
		return 2
	}

	// Still equal: random
	return uint8(1 + rand.Intn(2))
}

// GetMemberState returns a member's battle state (nil if not found).
func (bs *BattleState) GetMemberState(charID uint32) *MemberState {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	return bs.States[charID]
}

// IsAlive returns whether a member is alive.
func (bs *BattleState) IsAlive(charID uint32) bool {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	if s, ok := bs.States[charID]; ok {
		return s.Alive
	}
	return false
}

// IsFinished returns whether the battle has ended.
func (bs *BattleState) IsFinished() bool {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	return bs.Finished
}

// GetWinner returns the winning camp (0=draw, 1, 2).
func (bs *BattleState) GetWinner() uint8 {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	return bs.Winner
}

// GetScores returns the current kill scores.
func (bs *BattleState) GetScores() [3]int32 {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	return bs.Scores
}

// GetElapsedMS returns the elapsed time since battle start.
func (bs *BattleState) GetElapsedMS() int64 {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	now := time.Now().UnixMilli()
	elapsed := now - bs.StartTime
	if elapsed > bs.Duration {
		elapsed = bs.Duration
	}
	return elapsed
}

// MarkSettlementSent atomically marks settlement as sent. Returns true if this call changed it.
func (bs *BattleState) MarkSettlementSent() bool {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	if bs.SettlementSent {
		return false
	}
	bs.SettlementSent = true
	return true
}
