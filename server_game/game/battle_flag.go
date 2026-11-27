package game

import "math"

func (bs *BattleState) tickFlags(positions map[uint32]*MemberPos, now int64, result *TickResult) {
	const flagRadius = 60.0
	const scoreIntervalMS int64 = 3000

	winTarget := bs.WinTarget
	if winTarget <= 0 {
		winTarget = 1000
	}

	changed := false
	for _, flag := range bs.Flags {
		var c1, c2 int
		for memberID, state := range bs.States {
			if !state.Alive {
				continue
			}
			pos := positions[memberID]
			if pos == nil {
				continue
			}
			if math.Hypot(float64(pos.X-flag.X), float64(pos.Y-flag.Y)) <= flagRadius {
				if state.Camp == 1 {
					c1++
				} else if state.Camp == 2 {
					c2++
				}
			}
		}

		var leading uint8
		if c1 > c2 {
			leading = 1
		} else if c2 > c1 {
			leading = 2
		}

		if flag.Locked != 0 || leading == 0 || int32(leading) == flag.Camp {
			flag.CaptureCamp = 0
			flag.CaptureStartedAt = 0
		} else if leading != flag.CaptureCamp {
			flag.CaptureCamp = leading
			flag.CaptureStartedAt = now
		} else if now-flag.CaptureStartedAt >= flag.CaptureMS {
			flag.Camp = int32(leading)
			flag.CaptureCamp = 0
			flag.CaptureStartedAt = 0
			flag.ScoreDueAt = now + scoreIntervalMS
		}

		var progress int32
		if flag.CaptureCamp != 0 {
			secs := int32((now - flag.CaptureStartedAt) / 1000)
			maxSecs := int32(flag.CaptureMS / 1000)
			if secs > maxSecs {
				secs = maxSecs
			}
			if secs < 0 {
				secs = 0
			}
			if flag.CaptureCamp == 1 {
				progress = -secs
			} else {
				progress = secs
			}
		}
		wire := [4]int32{flag.Index, flag.Camp, flag.Locked, progress}
		if !flag.HasWire || wire != flag.LastWire {
			flag.LastWire = wire
			flag.HasWire = true
			changed = true
		}
	}

	// Check 3-flag double score bonus
	double := false
	if len(bs.Flags) == 3 && bs.Flags[0].Camp != 0 &&
		bs.Flags[0].Camp == bs.Flags[1].Camp && bs.Flags[1].Camp == bs.Flags[2].Camp {
		double = true
	}

	for _, flag := range bs.Flags {
		if flag.Camp > 0 && flag.Camp <= 2 && flag.ScoreDueAt > 0 && now >= flag.ScoreDueAt {
			camp := uint8(flag.Camp)
			pts := flag.Score
			if double {
				pts *= 2
			}
			rem := winTarget - bs.Scores[camp]
			if rem < 0 {
				rem = 0
			}
			if pts > rem {
				pts = rem
			}
			if pts > 0 {
				bs.Scores[camp] += pts
				result.FlagScores = append(result.FlagScores, FlagScoreEvent{
					Index: flag.Index,
					Camp:  flag.Camp,
					Gain:  pts,
				})
			}
			flag.ScoreDueAt = now + scoreIntervalMS
		}
	}

	if changed {
		snap := make([]FlagWireEvent, len(bs.Flags))
		for i, flag := range bs.Flags {
			snap[i] = FlagWireEvent{
				Index:    flag.LastWire[0],
				Camp:     flag.LastWire[1],
				Locked:   flag.LastWire[2],
				Progress: flag.LastWire[3],
			}
		}
		result.FlagSnapshot = snap
	}

	for _, camp := range []uint8{1, 2} {
		if bs.Scores[camp] >= winTarget {
			bs.Finished = true
			bs.Winner = camp
			result.GameOver = true
			result.Winner = camp
			result.Scores = bs.Scores
			result.ElapsedMS = int32(now - bs.StartTime)
			break
		}
	}
}

// tickRepairBoxes handles iType==6 HP boxes: 5s heal (4% MaxHP/sec) with 15s tank cooldown.
