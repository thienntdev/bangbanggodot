package game

import (
	"encoding/json"
	"fmt"
	"log"
	"math"
	"os"
	"path/filepath"
	"strconv"
)

// MapNPC represents a destructible map object (obstacle, turret, repair box, base).
type MapNPC struct {
	ID       uint32 // (14<<24) | instanceID — matches client 234881024|inst
	Template uint32 // NpcTemplate ID
	X        int16  // center X
	Y        int16  // center Y
	HP       int32  // current HP
	MaxHP    int32  // max HP
	Camp     uint8  // 0=neutral, 1=camp1, 2=camp2
	Width    int16  // collision width
	Height   int16  // collision height
	Type     int    // iType: 1=obstacle, 3=base, 4=turret, 6=repair box
	Alive    bool

	// Active repair state for iType=6 HP boxes
	RepairTarget    uint32
	RepairTicksLeft int
	RepairNextAt    int64

	// Turret AI state for iType=4
	Attack           int32
	EnergyAtk        int32
	FireIntervalMS   int32
	AlertRange       int32
	TurretSkill      uint32
	TurretNextShotAt int64
	TurretTargetID   uint32
	TurretHits       int
}

// MapNPCHitResult holds the result of a bullet hitting a map object.
type MapNPCHitResult struct {
	NpcID uint32
	HP    int32 // current HP after damage
	Dead  bool
	X     int16
	Y     int16
}

const npcKindShift = 14 << 24 // 234881024 = 0x0E000000 — matches client's 234881024|instanceID

// LoadMapNPCs loads NPCs from a map JSON file and returns them keyed by ID.
func LoadMapNPCs(staticDir string, mapID uint32) map[uint32]*MapNPC {
	mapPath := filepath.Join(staticDir, "godot", "a", "m", fmt.Sprintf("%d", mapID), "map.json")
	data, err := os.ReadFile(mapPath)
	if err != nil {
		log.Printf("[map_objects] warning: cannot read %s: %v", mapPath, err)
		return nil
	}

	var doc struct {
		Visual struct {
			NPCTemplates map[string]json.RawMessage `json:"npc_templates"`
		} `json:"visual"`
		Chunks []struct {
			Tag  int             `json:"tag"`
			Data json.RawMessage `json:"data"`
		} `json:"chunks"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		log.Printf("[map_objects] warning: invalid map JSON %s: %v", mapPath, err)
		return nil
	}

	// Parse NPC templates → {templateID: {iHp, iWidth, iHeight, iType, turret stats}}
	type npcTemplate struct {
		HP           int32
		Width        int16
		Height       int16
		Type         int
		Attack       int32
		EnergyAtk    int32
		FireInterval int32
		AlertRange   int32
		PropsID      uint32
	}
	templates := make(map[uint32]*npcTemplate)
	for key, raw := range doc.Visual.NPCTemplates {
		tid, err := strconv.ParseUint(key, 10, 32)
		if err != nil {
			continue
		}
		var row map[string]interface{}
		if err := json.Unmarshal(raw, &row); err != nil {
			continue
		}
		tpl := &npcTemplate{}
		if v, ok := row["iHp"]; ok {
			tpl.HP = parseInt32(v)
		}
		if v, ok := row["iWidth"]; ok {
			tpl.Width = int16(parseInt32(v))
		}
		if v, ok := row["iHeight"]; ok {
			tpl.Height = int16(parseInt32(v))
		}
		if v, ok := row["iType"]; ok {
			tpl.Type = int(parseInt32(v))
		}
		if v, ok := row["iAttack"]; ok {
			tpl.Attack = parseInt32(v)
		}
		if v, ok := row["iEgAtk"]; ok {
			tpl.EnergyAtk = parseInt32(v)
		}
		if v, ok := row["nInterval"]; ok {
			tpl.FireInterval = parseInt32(v)
		}
		if v, ok := row["iAlertRange"]; ok {
			tpl.AlertRange = parseInt32(v)
		}
		if v, ok := row["nPropsId"]; ok {
			tpl.PropsID = uint32(parseInt32(v))
		}
		templates[uint32(tid)] = tpl
	}

	// Parse NPC instances from chunks
	result := make(map[uint32]*MapNPC)
	for _, chunk := range doc.Chunks {
		var chunkData struct {
			NPCs []struct {
				InstanceID uint32 `json:"nInstanceId"`
				TemplateID uint32 `json:"templetId"`
				CenterX    int16  `json:"iCenterX"`
				CenterY    int16  `json:"iCenterY"`
				Camp       uint8  `json:"iCamp"`
			} `json:"npcs"`
		}
		if err := json.Unmarshal(chunk.Data, &chunkData); err != nil || len(chunkData.NPCs) == 0 {
			continue
		}
		for _, npc := range chunkData.NPCs {
			tpl := templates[npc.TemplateID]
			if tpl == nil || tpl.HP <= 0 {
				continue
			}
			id := uint32(npcKindShift) | npc.InstanceID
			camp := npc.Camp
			// Ordinary obstacles (iType=1) are neutral (camp=0)
			if tpl.Type == 1 {
				camp = 0
			}
			fireInterval := tpl.FireInterval
			if fireInterval <= 0 {
				fireInterval = 1000
			}
			alertRange := tpl.AlertRange
			if alertRange <= 0 {
				alertRange = 400
			}
			result[id] = &MapNPC{
				ID:             id,
				Template:       npc.TemplateID,
				X:              npc.CenterX,
				Y:              npc.CenterY,
				HP:             tpl.HP,
				MaxHP:          tpl.HP,
				Camp:           camp,
				Width:          tpl.Width,
				Height:         tpl.Height,
				Type:           tpl.Type,
				Alive:          true,
				Attack:         tpl.Attack,
				EnergyAtk:      tpl.EnergyAtk,
				FireIntervalMS: fireInterval,
				AlertRange:     alertRange,
				TurretSkill:    tpl.PropsID,
			}
		}
	}

	log.Printf("[map_objects] loaded %d NPCs from map %d", len(result), mapID)
	return result
}

// AirDropPoint represents a map air-drop spawn coordinate (chunk tag 5).
type AirDropPoint struct {
	X int16
	Y int16
}

// LoadMapAirDrops loads air-drop spawn points (chunk tag 5) from map.json.
func LoadMapAirDrops(staticDir string, mapID uint32) []AirDropPoint {
	mapPath := filepath.Join(staticDir, "godot", "a", "m", fmt.Sprintf("%d", mapID), "map.json")
	data, err := os.ReadFile(mapPath)
	if err != nil {
		return nil
	}
	var doc struct {
		Chunks []struct {
			Tag  int             `json:"tag"`
			Data json.RawMessage `json:"data"`
		} `json:"chunks"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		return nil
	}
	var pts []AirDropPoint
	for _, chunk := range doc.Chunks {
		if chunk.Tag != 5 {
			continue
		}
		var chunkData struct {
			Points []struct {
				X int16 `json:"iCenterX"`
				Y int16 `json:"iCenterY"`
			} `json:"points"`
		}
		if err := json.Unmarshal(chunk.Data, &chunkData); err == nil {
			for _, p := range chunkData.Points {
				pts = append(pts, AirDropPoint{X: p.X, Y: p.Y})
			}
		}
	}
	return pts
}

// parseInt32 parses various JSON value types (string or number) to int32.
func parseInt32(v interface{}) int32 {
	switch val := v.(type) {
	case string:
		n, _ := strconv.ParseInt(val, 10, 32)
		return int32(n)
	case float64:
		return int32(val)
	case json.Number:
		n, _ := val.Int64()
		return int32(n)
	}
	return 0
}

// CheckBulletNPCCollisionSegment checks if the segment (x1,y1)->(x2,y2) hits any alive NPC.
// Returns the earliest hit NPC and fraction along the segment, or nil if no hit.
func CheckBulletNPCCollisionSegment(npcs map[uint32]*MapNPC, x1, y1, x2, y2 float64, bulletCamp uint8) (*MapNPCHitResult, float64) {
	var best *MapNPCHitResult
	bestFrac := 2.0
	for _, npc := range npcs {
		if !npc.Alive {
			continue
		}
		if npc.Camp != 0 && npc.Camp == bulletCamp {
			continue
		}
		halfW := float64(npc.Width) / 2.0
		halfH := float64(npc.Height) / 2.0
		if halfW <= 0 {
			halfW = 36
		}
		if halfH <= 0 {
			halfH = 36
		}
		w := WallRect{
			Left:   float64(npc.X) - halfW,
			Top:    float64(npc.Y) - halfH,
			Right:  float64(npc.X) + halfW,
			Bottom: float64(npc.Y) + halfH,
		}
		if hit, frac := segmentHitsSingleRect(w, x1, y1, x2, y2); hit && frac < bestFrac {
			bestFrac = frac
			best = &MapNPCHitResult{
				NpcID: npc.ID,
				HP:    npc.HP,
				Dead:  false,
				X:     npc.X,
				Y:     npc.Y,
			}
		}
	}
	return best, bestFrac
}

// SegmentCircleContact returns (true, earliestFraction) if segment (x1,y1)->(x2,y2) intersects circle (cx,cy,radius).
func SegmentCircleContact(x1, y1, x2, y2, cx, cy, radius float64) (bool, float64) {
	rx := x1 - cx
	ry := y1 - cy
	c := rx*rx + ry*ry - radius*radius
	if c <= 0 {
		return true, 0
	}
	dx := x2 - x1
	dy := y2 - y1
	a := dx*dx + dy*dy
	if a == 0 {
		return false, 1.0
	}
	b := 2 * (rx*dx + ry*dy)
	disc := b*b - 4*a*c
	if disc < 0 {
		return false, 1.0
	}
	t := (-b - math.Sqrt(disc)) / (2 * a)
	if t >= 0 && t <= 1 {
		return true, t
	}
	return false, 1.0
}

// MapFlag represents a capture point on occupy maps (ModeType == 2).
type MapFlag struct {
	Index            int32
	X                int16
	Y                int16
	Camp             int32 // 0=neutral, 1=camp1, 2=camp2
	Locked           int32
	Score            int32
	CaptureMS        int64
	CaptureCamp      uint8
	CaptureStartedAt int64
	ScoreDueAt       int64
	LastWire         [4]int32
	HasWire          bool
}

// LoadMapFlags loads capture flags (chunk tag 7) from map.json for occupy maps.
func LoadMapFlags(staticDir string, mapID uint32) []*MapFlag {
	mapPath := filepath.Join(staticDir, "godot", "a", "m", fmt.Sprintf("%d", mapID), "map.json")
	data, err := os.ReadFile(mapPath)
	if err != nil {
		return nil
	}
	var doc struct {
		Chunks []struct {
			Tag  int             `json:"tag"`
			Data json.RawMessage `json:"data"`
		} `json:"chunks"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		return nil
	}
	for _, chunk := range doc.Chunks {
		if chunk.Tag != 7 {
			continue
		}
		var chunkData struct {
			Flags []struct {
				Index      int32 `json:"iIndex"`
				CenterX    int16 `json:"iCenterX"`
				CenterY    int16 `json:"iCenterY"`
				Camp       int32 `json:"iCamp"`
				IsLock     int32 `json:"iIsLock"`
				AwardPoint int32 `json:"iControlAwardPoint"`
				ControlSec int64 `json:"iControlSecond"`
			} `json:"flags"`
		}
		if err := json.Unmarshal(chunk.Data, &chunkData); err != nil || len(chunkData.Flags) == 0 {
			return nil
		}
		flags := make([]*MapFlag, 0, len(chunkData.Flags))
		for _, f := range chunkData.Flags {
			capMS := f.ControlSec * 1000
			if capMS <= 0 {
				capMS = 4000
			}
			pts := f.AwardPoint
			if pts <= 0 {
				pts = 25
			}
			flags = append(flags, &MapFlag{
				Index:     f.Index,
				X:         f.CenterX,
				Y:         f.CenterY,
				Camp:      f.Camp,
				Locked:    f.IsLock,
				Score:     pts,
				CaptureMS: capMS,
			})
		}
		log.Printf("[map_objects] loaded %d capture flags for map %d", len(flags), mapID)
		return flags
	}
	return nil
}

// WallRect represents an axis-aligned solid wall rectangle from map.json chunk tag 1 (blocks).
type WallRect struct {
	Left, Top, Right, Bottom float64
}

// MapWalls holds the two sets of wall rectangles loaded from a map:
//   - BulletWalls: blocks bullets (solid walls only, instanceId == -1 and chunk-1 blocks)
//   - MovementWalls: blocks tank movement (solid walls + water grids, instanceId == -1 or -2)
//
// Python reference: battle_map.py uses self.walls (bullets) vs self.movement_walls (movement).
// Water grids (instanceId == -2) block vehicle movement but let bullets pass through.
type MapWalls struct {
	BulletWalls   []WallRect
	MovementWalls []WallRect
}

// LoadMapWalls loads wall rectangles from map.json and separates them into
// bullet-blocking (solid only) and movement-blocking (solid + water) sets.
// chunk tag 1 (blocks) → both sets; chunk tag 6 grids: instanceId -1 → both, -2 → movement only.
func LoadMapWalls(staticDir string, mapID uint32) MapWalls {
	mapPath := filepath.Join(staticDir, "godot", "a", "m", fmt.Sprintf("%d", mapID), "map.json")
	data, err := os.ReadFile(mapPath)
	if err != nil {
		return MapWalls{}
	}
	var doc struct {
		Header struct {
			MapWidth int `json:"mapWidth"`
		} `json:"header"`
		Chunks []struct {
			Tag  int             `json:"tag"`
			Data json.RawMessage `json:"data"`
		} `json:"chunks"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		return MapWalls{}
	}
	var bulletWalls, movementOnly []WallRect
	for _, chunk := range doc.Chunks {
		if chunk.Tag == 1 {
			var chunkData struct {
				Blocks []struct {
					CenterX float64 `json:"centerX"`
					CenterY float64 `json:"centerY"`
					Width   float64 `json:"width"`
					Height  float64 `json:"height"`
				} `json:"blocks"`
			}
			if err := json.Unmarshal(chunk.Data, &chunkData); err == nil {
				for _, b := range chunkData.Blocks {
					if b.Width <= 0 || b.Height <= 0 {
						continue
					}
					bulletWalls = append(bulletWalls, WallRect{
						Left:   b.CenterX - b.Width/2.0,
						Top:    b.CenterY - b.Height/2.0,
						Right:  b.CenterX + b.Width/2.0,
						Bottom: b.CenterY + b.Height/2.0,
					})
				}
			}
		} else if chunk.Tag == 6 && doc.Header.MapWidth >= 24 {
			var chunkData struct {
				Grids []struct {
					GridIndex  int `json:"gridIndex"`
					InstanceID int `json:"instanceId"`
				} `json:"grids"`
			}
			if err := json.Unmarshal(chunk.Data, &chunkData); err == nil {
				cols := doc.Header.MapWidth / 24
				for _, g := range chunkData.Grids {
					if g.GridIndex < 0 {
						continue
					}
					if g.InstanceID == -1 {
						// Solid wall: blocks both bullets and movement
						col := g.GridIndex % cols
						row := g.GridIndex / cols
						bulletWalls = append(bulletWalls, WallRect{
							Left:   float64(col * 24),
							Top:    float64(row * 24),
							Right:  float64((col + 1) * 24),
							Bottom: float64((row + 1) * 24),
						})
					} else if g.InstanceID == -2 {
						// Water: blocks movement only, bullets pass through
						col := g.GridIndex % cols
						row := g.GridIndex / cols
						movementOnly = append(movementOnly, WallRect{
							Left:   float64(col * 24),
							Top:    float64(row * 24),
							Right:  float64((col + 1) * 24),
							Bottom: float64((row + 1) * 24),
						})
					}
					// <=-3 = bush (visual only, blocks nothing)
					// >=0 = NPC (handled separately)
				}
			}
		}
	}
	// MovementWalls = all bullet walls + water-only walls
	moveWalls := make([]WallRect, 0, len(bulletWalls)+len(movementOnly))
	moveWalls = append(moveWalls, bulletWalls...)
	moveWalls = append(moveWalls, movementOnly...)

	log.Printf("[map_objects] loaded %d bullet walls + %d water walls = %d movement walls for map %d",
		len(bulletWalls), len(movementOnly), len(moveWalls), mapID)
	return MapWalls{BulletWalls: bulletWalls, MovementWalls: moveWalls}
}

// NPCMovementWalls builds additional movement wall rects from alive NPC bounding boxes.
// Python reference: battle_map.py._walk_objects adds NPC rects to movement_walls.
func NPCMovementWalls(npcs map[uint32]*MapNPC) []WallRect {
	if len(npcs) == 0 {
		return nil
	}
	var walls []WallRect
	for _, npc := range npcs {
		if !npc.Alive {
			continue
		}
		halfW := float64(npc.Width) / 2.0
		halfH := float64(npc.Height) / 2.0
		if halfW <= 0 {
			halfW = 36
		}
		if halfH <= 0 {
			halfH = 36
		}
		walls = append(walls, WallRect{
			Left:   float64(npc.X) - halfW,
			Top:    float64(npc.Y) - halfH,
			Right:  float64(npc.X) + halfW,
			Bottom: float64(npc.Y) + halfH,
		})
	}
	return walls
}

// PointInsideWall checks if a point (px, py) is inside any wall rectangle.
// Used for movement validation — rejects positions inside solid walls or water.
func PointInsideWall(walls []WallRect, px, py float64) bool {
	for _, w := range walls {
		if px >= w.Left && px <= w.Right && py >= w.Top && py <= w.Bottom {
			return true
		}
	}
	return false
}

func segmentHitsSingleRect(w WallRect, x1, y1, x2, y2 float64) (bool, float64) {
	dx := x2 - x1
	dy := y2 - y1
	low, high := 0.0, 1.0
	if dx == 0 {
		if x1 < w.Left || x1 > w.Right {
			return false, 1.0
		}
	} else {
		t1 := (w.Left - x1) / dx
		t2 := (w.Right - x1) / dx
		if t1 > t2 {
			t1, t2 = t2, t1
		}
		if t1 > low {
			low = t1
		}
		if t2 < high {
			high = t2
		}
		if low > high {
			return false, 1.0
		}
	}
	if dy == 0 {
		if y1 < w.Top || y1 > w.Bottom {
			return false, 1.0
		}
	} else {
		t1 := (w.Top - y1) / dy
		t2 := (w.Bottom - y1) / dy
		if t1 > t2 {
			t1, t2 = t2, t1
		}
		if t1 > low {
			low = t1
		}
		if t2 < high {
			high = t2
		}
		if low > high {
			return false, 1.0
		}
	}
	return true, low
}

// SegmentHitsWall checks if the segment (x1,y1)->(x2,y2) intersects any wall rectangle.
// Returns (true, earliestFraction) using slab clipping (matching Python combat_geometry.rect_contact).
func SegmentHitsWall(walls []WallRect, x1, y1, x2, y2 float64) (bool, float64) {
	if len(walls) == 0 {
		return false, 1.0
	}
	hit := false
	first := 1.0
	for _, w := range walls {
		if h, frac := segmentHitsSingleRect(w, x1, y1, x2, y2); h && (!hit || frac < first) {
			hit = true
			first = frac
			if first == 0 {
				return true, 0
			}
		}
	}
	return hit, first
}
