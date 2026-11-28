package game

// Surrender vote system for battles.

const (
	VoteDurationMS int64 = 30000 // 30 seconds to vote
	VoteCooldownMS int64 = 60000 // 60 seconds between votes
)

// SurrenderVote tracks an active surrender vote.
type SurrenderVote struct {
	Sponsor    uint32
	TeamIDs    []uint32
	Votes      map[uint32]bool // charID -> agree
	StartedAt  int64           // unix ms
	EndsAt     int64           // unix ms
	Resolved   bool
}

// SurrenderVoteResult is returned when starting or casting a vote.
type SurrenderVoteResult struct {
	Started       bool
	OnCooldown    bool
	AlreadyActive bool
	Passed        bool
	Failed        bool
	ValidCount    uint8
	VoteSlice     []uint8 // per-team-member: 0=not voted, 1=deny, 2=agree
	Sponsor       uint32
	TeamIDs       []uint32
}

// StartSurrenderVote begins a new vote. Returns result.
func (bs *BattleState) StartSurrenderVote(sponsor uint32, teamIDs []uint32, nowMS int64) SurrenderVoteResult {
	bs.mu.Lock()
	defer bs.mu.Unlock()

	// Check cooldown
	if nowMS < bs.VoteCooldown {
		return SurrenderVoteResult{OnCooldown: true}
	}

	// Check if vote already active
	if bs.Vote != nil && !bs.Vote.Resolved && nowMS < bs.Vote.EndsAt {
		return SurrenderVoteResult{AlreadyActive: true}
	}

	endAt := nowMS + VoteDurationMS
	bs.Vote = &SurrenderVote{
		Sponsor:   sponsor,
		TeamIDs:   teamIDs,
		Votes:     map[uint32]bool{sponsor: true}, // sponsor auto-agrees
		StartedAt: nowMS,
		EndsAt:    endAt,
	}
	bs.VoteEndAt = endAt

	return SurrenderVoteResult{
		Started:    true,
		ValidCount: uint8(len(teamIDs)),
		Sponsor:    sponsor,
		TeamIDs:    teamIDs,
	}
}

// CastSurrenderVote records a player's vote.
func (bs *BattleState) CastSurrenderVote(charID uint32, agree bool, nowMS int64) SurrenderVoteResult {
	bs.mu.Lock()
	defer bs.mu.Unlock()

	v := bs.Vote
	if v == nil || v.Resolved || nowMS > v.EndsAt {
		return SurrenderVoteResult{}
	}

	v.Votes[charID] = agree

	// Build vote slice for broadcast
	voteSlice := make([]uint8, len(v.TeamIDs))
	agreeCount := 0
	denyCount := 0
	for i, mid := range v.TeamIDs {
		if voted, ok := v.Votes[mid]; ok {
			if voted {
				voteSlice[i] = 2
				agreeCount++
			} else {
				voteSlice[i] = 1
				denyCount++
			}
		}
	}

	result := SurrenderVoteResult{
		ValidCount: uint8(len(v.TeamIDs)),
		VoteSlice:  voteSlice,
		Sponsor:    v.Sponsor,
		TeamIDs:    v.TeamIDs,
	}

	total := len(v.TeamIDs)
	majority := total/2 + 1

	if agreeCount >= majority {
		result.Passed = true
		v.Resolved = true
	} else if denyCount >= majority || len(v.Votes) >= total {
		result.Failed = true
		v.Resolved = true
		bs.VoteCooldown = nowMS + VoteCooldownMS
	}

	return result
}

// CheckVoteTimeout checks if the current vote has timed out. Called from tick loop.
func (bs *BattleState) CheckVoteTimeout(nowMS int64) (SurrenderVoteResult, bool) {
	bs.mu.Lock()
	defer bs.mu.Unlock()

	v := bs.Vote
	if v == nil || v.Resolved || nowMS < v.EndsAt {
		return SurrenderVoteResult{}, false
	}

	// Vote expired — tally
	agreeCount := 0
	for _, voted := range v.Votes {
		if voted {
			agreeCount++
		}
	}

	v.Resolved = true
	total := len(v.TeamIDs)
	majority := total/2 + 1

	result := SurrenderVoteResult{
		ValidCount: uint8(total),
		Sponsor:    v.Sponsor,
		TeamIDs:    v.TeamIDs,
	}

	if agreeCount >= majority {
		result.Passed = true
	} else {
		result.Failed = true
		bs.VoteCooldown = nowMS + VoteCooldownMS
	}

	return result, true
}

// ForceEndSurrender forces the battle to end due to surrender.
func (bs *BattleState) ForceEndSurrender(winner uint8) {
	bs.ForceEnd(winner)
}

// GetBattleSeconds converts a unix ms timestamp to seconds since battle start.
func (bs *BattleState) GetBattleSeconds(timestampMS int64) uint32 {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	if timestampMS <= bs.StartTime {
		return 0
	}
	return uint32((timestampMS - bs.StartTime) / 1000)
}

// GetVoteCooldownSeconds returns seconds until next vote is allowed.
func (bs *BattleState) GetVoteCooldownSeconds(nowMS int64) uint32 {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	if nowMS >= bs.VoteCooldown {
		return 0
	}
	return uint32((bs.VoteCooldown - nowMS) / 1000)
}

// GetWinType returns how the battle ended:
// 0=time/score, 1=forfeit/surrender, 2=disconnect
func (bs *BattleState) GetWinType() uint8 {
	bs.mu.Lock()
	defer bs.mu.Unlock()
	if bs.Vote != nil && bs.Vote.Resolved {
		return 1 // surrender
	}
	return 0 // normal
}
