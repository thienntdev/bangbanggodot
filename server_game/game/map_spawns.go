package game

import "math/rand"

// AllMapIDs returns a slice of all configured map IDs.
func AllMapIDs() []uint32 {
	ids := make([]uint32, 0, len(mapSpawnConfigs))
	for id := range mapSpawnConfigs {
		ids = append(ids, id)
	}
	return ids
}

// RandomMapID picks a random map ID from the configured maps.
func RandomMapID() uint32 {
	ids := AllMapIDs()
	if len(ids) == 0 {
		return 1
	}
	return ids[rand.Intn(len(ids))]
}

// MapBattleRule holds per-map duration and win target from client_MapTemplate_table.
type MapBattleRule struct {
	DurationSec int64
	WinTarget   int32
	ModeType    uint8
}

var mapBattleRules = map[uint32]MapBattleRule{
	1:    {DurationSec: 240, WinTarget: 25, ModeType: 3},
	4:    {DurationSec: 240, WinTarget: 25, ModeType: 3},
	7:    {DurationSec: 600, WinTarget: 1000, ModeType: 2},
	9:    {DurationSec: 600, WinTarget: 1000, ModeType: 2},
	10:   {DurationSec: 600, WinTarget: 1000, ModeType: 2},
	12:   {DurationSec: 900, WinTarget: 0, ModeType: 1},
	14:   {DurationSec: 900, WinTarget: 0, ModeType: 1},
	17:   {DurationSec: 240, WinTarget: 25, ModeType: 3},
	18:   {DurationSec: 210, WinTarget: 25, ModeType: 3},
	19:   {DurationSec: 240, WinTarget: 25, ModeType: 3},
	20:   {DurationSec: 240, WinTarget: 25, ModeType: 3},
	21:   {DurationSec: 240, WinTarget: 25, ModeType: 3},
	30:   {DurationSec: 150, WinTarget: 100, ModeType: 4},
	34:   {DurationSec: 210, WinTarget: 25, ModeType: 3},
	35:   {DurationSec: 240, WinTarget: 25, ModeType: 3},
	36:   {DurationSec: 240, WinTarget: 25, ModeType: 3},
	37:   {DurationSec: 600, WinTarget: 1000, ModeType: 2},
	40:   {DurationSec: 150, WinTarget: 100, ModeType: 4},
	50:   {DurationSec: 900, WinTarget: 0, ModeType: 1},
	70:   {DurationSec: 900, WinTarget: 0, ModeType: 1},
	101:  {DurationSec: 0, WinTarget: 3, ModeType: 3},
	102:  {DurationSec: 0, WinTarget: 0, ModeType: 1},
	103:  {DurationSec: 900, WinTarget: 1000, ModeType: 2},
	104:  {DurationSec: 0, WinTarget: 7, ModeType: 3},
	130:  {DurationSec: 300, WinTarget: 25, ModeType: 7},
	150:  {DurationSec: 180, WinTarget: 25, ModeType: 3},
	151:  {DurationSec: 180, WinTarget: 25, ModeType: 3},
	152:  {DurationSec: 180, WinTarget: 25, ModeType: 3},
	153:  {DurationSec: 90, WinTarget: 25, ModeType: 3},
	166:  {DurationSec: 900, WinTarget: 0, ModeType: 1},
	167:  {DurationSec: 900, WinTarget: 0, ModeType: 1},
	168:  {DurationSec: 900, WinTarget: 0, ModeType: 1},
	169:  {DurationSec: 900, WinTarget: 0, ModeType: 1},
	170:  {DurationSec: 600, WinTarget: 1000, ModeType: 2},
	175:  {DurationSec: 600, WinTarget: 1000, ModeType: 2},
	177:  {DurationSec: 600, WinTarget: 1000, ModeType: 2},
	2002: {DurationSec: 600, WinTarget: 0, ModeType: 1},
}

// GetMapBattleRule returns (durationMS, winTarget, modeType) for mapID from MapTemplate.
func GetMapBattleRule(mapID uint32) (int64, int32, uint8) {
	if r, ok := mapBattleRules[mapID]; ok {
		dur := r.DurationSec * 1000
		if dur <= 0 {
			dur = DefaultDuration
		}
		wt := r.WinTarget
		if wt <= 0 {
			wt = WinKills
		}
		return dur, wt, r.ModeType
	}
	return DefaultDuration, WinKills, 3
}

// MapSpawnConfig holds spawn and respawn points per camp for a map.
type MapSpawnConfig struct {
	Spawns   [2][]Point // [0]=camp1, [1]=camp2 (initial spawn)
	Respawns [2][]Point // [0]=camp1, [1]=camp2 (respawn after death)
}

// Point is a 2D coordinate.
type Point struct {
	X, Y int16
}

// Spawn returns the initial spawn position for a camp (1 or 2) and player index.
func (c *MapSpawnConfig) Spawn(camp uint8, index int) Point {
	idx := int(camp) - 1
	if idx < 0 || idx > 1 || len(c.Spawns[idx]) == 0 {
		return Point{250, 500} // fallback
	}
	return c.Spawns[idx][index%len(c.Spawns[idx])]
}

// Respawn returns the respawn position for a camp (1 or 2) and player index.
func (c *MapSpawnConfig) Respawn(camp uint8, index int) Point {
	idx := int(camp) - 1
	if idx < 0 || idx > 1 || len(c.Respawns[idx]) == 0 {
		// Fall back to initial spawn if no respawn points defined
		return c.Spawn(camp, index)
	}
	return c.Respawns[idx][index%len(c.Respawns[idx])]
}

// defaultSpawnConfig is used for unknown maps.
var defaultSpawnConfig = &MapSpawnConfig{
	Spawns: [2][]Point{
		{{204, 468}, {204, 564}, {204, 660}, {300, 516}, {300, 612}},
		{{1956, 948}, {1956, 852}, {1956, 756}, {1860, 804}, {1860, 900}},
	},
	Respawns: [2][]Point{
		{{252, 564}, {252, 492}, {252, 636}, {252, 420}, {252, 708}},
		{{1908, 852}, {1908, 924}, {1908, 780}, {1908, 996}, {1908, 708}},
	},
}

// GetMapSpawnConfig returns spawn config for a map ID (from Python SQLite data).
func GetMapSpawnConfig(mapID uint32) *MapSpawnConfig {
	if cfg, ok := mapSpawnConfigs[mapID]; ok {
		return cfg
	}
	return defaultSpawnConfig
}

// mapSpawnConfigs holds spawn data extracted from Python's SQLite battle_map_* settings.
var mapSpawnConfigs = map[uint32]*MapSpawnConfig{
	1: {
		Spawns: [2][]Point{
			{{204, 468}, {204, 564}, {204, 660}, {300, 516}, {300, 612}},
			{{1956, 948}, {1956, 852}, {1956, 756}, {1860, 804}, {1860, 900}},
		},
		Respawns: [2][]Point{
			{{252, 564}, {252, 492}, {252, 636}, {252, 420}, {252, 708}},
			{{1908, 852}, {1908, 924}, {1908, 780}, {1908, 996}, {1908, 708}},
		},
	},
	4: {
		Spawns: [2][]Point{
			{{396, 612}, {396, 756}, {396, 1188}, {396, 180}, {396, 1260}, {396, 108}},
			{{1404, 756}, {1404, 612}, {1404, 1188}, {1404, 1260}, {1404, 180}, {1404, 108}},
		},
		Respawns: [2][]Point{
			{{180, 876}, {180, 972}, {276, 924}, {180, 492}, {180, 396}, {276, 444}},
			{{1620, 492}, {1620, 396}, {1524, 444}, {1620, 876}, {1620, 972}, {1524, 924}},
		},
	},
	7: {
		Spawns: [2][]Point{
			{{1404, 1236}, {1404, 996}, {1548, 1116}, {1548, 876}, {1404, 756}},
			{{1548, 1236}, {1404, 1116}, {1548, 996}, {1404, 876}, {1548, 756}},
		},
		Respawns: [2][]Point{
			{{1404, 1188}},
			{{1524, 1044}},
		},
	},
	9: {
		Spawns: [2][]Point{
			{{1356, 1500}, {1356, 1596}, {1356, 1692}, {1356, 1788}, {1356, 1884}},
			{{1812, 1356}, {1908, 1356}, {2004, 1356}, {2100, 1356}, {2196, 1356}},
		},
		Respawns: [2][]Point{
			{{1644, 1788}, {2220, 1788}, {1932, 1596}},
			{{2220, 1596}, {1644, 1596}, {1932, 1788}},
		},
	},
	10: {
		Spawns: [2][]Point{
			{{468, 660}, {468, 588}, {468, 732}, {468, 516}, {468, 804}},
			{{2412, 660}, {2412, 588}, {2412, 732}, {2412, 516}, {2412, 804}},
		},
		Respawns: [2][]Point{
			{{156, 660}, {156, 588}, {156, 732}, {156, 516}, {156, 804}},
			{{2724, 660}, {2724, 588}, {2724, 732}, {2724, 516}, {2724, 804}},
		},
	},
	12: {
		Spawns: [2][]Point{
			{{156, 1260}, {84, 1260}, {156, 1188}, {156, 1332}, {84, 1188}},
			{{1836, 348}, {1908, 348}, {1836, 420}, {1836, 276}, {1908, 420}},
		},
		Respawns: [2][]Point{
			{{156, 1356}, {84, 1356}, {156, 1284}, {84, 1284}, {84, 1428}},
			{{1836, 252}, {1908, 252}, {1836, 324}, {1908, 324}, {1908, 180}},
		},
	},
	14: {
		Spawns: [2][]Point{
			{{396, 1116}, {396, 1188}, {468, 1116}, {444, 1044}, {468, 1188}},
			{{2268, 372}, {2196, 372}, {2268, 444}, {2340, 420}, {2196, 444}},
		},
		Respawns: [2][]Point{
			{{396, 1188}, {396, 1116}, {468, 1188}, {444, 1260}, {468, 1116}},
			{{2196, 372}, {2196, 444}, {2268, 372}, {2124, 420}, {2268, 444}},
		},
	},
	17: {
		Spawns: [2][]Point{
			{{156, 516}, {156, 588}, {156, 660}, {156, 732}, {156, 804}},
			{{2532, 732}, {2532, 828}, {2532, 516}, {2532, 588}, {2532, 660}},
		},
		Respawns: [2][]Point{
			{{252, 636}, {252, 756}, {348, 684}, {252, 540}, {348, 588}},
			{{2436, 732}, {2436, 636}, {2436, 540}, {2340, 588}, {2340, 684}},
		},
	},
	18: {
		Spawns: [2][]Point{
			{{372, 396}, {372, 492}, {372, 588}, {300, 588}, {228, 588}},
			{{1836, 1188}, {1764, 1188}, {1692, 1188}, {1692, 1260}, {1692, 1332}},
		},
		Respawns: [2][]Point{
			{{300, 540}},
			{{1740, 1260}},
		},
	},
	19: {
		Spawns: [2][]Point{
			{{516, 372}, {516, 444}, {516, 516}, {444, 516}, {588, 516}},
			{{2004, 1860}, {1932, 1860}, {1860, 1860}, {1860, 1932}, {1860, 2004}},
		},
		Respawns: [2][]Point{
			{{588, 372}, {588, 444}, {588, 588}, {516, 588}, {444, 588}},
			{{1788, 1860}, {1788, 1932}, {1788, 2004}, {1812, 1788}, {1884, 1788}},
		},
	},
	20: {
		Spawns: [2][]Point{
			{{420, 660}, {420, 732}, {420, 804}, {420, 588}, {420, 876}},
			{{1932, 708}, {1932, 780}, {1932, 852}, {1932, 636}, {1932, 924}},
		},
		Respawns: [2][]Point{
			{{348, 732}, {348, 660}, {348, 804}, {420, 780}, {420, 684}},
			{{2004, 780}, {1932, 708}, {1932, 780}, {1932, 852}, {2004, 852}},
		},
	},
	21: {
		Spawns: [2][]Point{
			{{300, 156}, {300, 228}, {300, 300}, {228, 300}, {156, 300}},
			{{1860, 1140}, {1932, 1140}, {2004, 1140}, {1860, 1212}, {1860, 1284}},
		},
		Respawns: [2][]Point{
			{{324, 324}, {324, 252}, {324, 396}, {252, 324}, {396, 324}},
			{{1836, 1116}, {1836, 1188}, {1836, 1044}, {1908, 1116}, {1764, 1116}},
		},
	},
	30: {
		Spawns: [2][]Point{
			{{156, 156}, {156, 252}, {252, 156}, {348, 156}, {156, 348}},
			{{2052, 1548}, {2052, 1452}, {2052, 1356}, {1956, 1548}, {1860, 1548}},
		},
		Respawns: [2][]Point{
			{{348, 156}, {252, 156}, {156, 156}, {156, 252}, {156, 348}},
			{{2052, 1356}, {2052, 1452}, {2052, 1548}, {1956, 1548}, {1860, 1548}},
		},
	},
	34: {
		Spawns: [2][]Point{
			{{372, 900}, {372, 660}, {372, 444}, {372, 1140}, {372, 1380}},
			{{1956, 444}, {1956, 684}, {1956, 900}, {1956, 1140}, {1956, 1380}},
		},
		Respawns: [2][]Point{
			{{372, 444}, {372, 660}, {372, 900}, {372, 1140}, {372, 1380}},
			{{1956, 444}, {1956, 684}, {1956, 900}, {1956, 1140}, {1956, 1380}},
		},
	},
	35: {
		Spawns: [2][]Point{
			{{396, 2028}, {516, 2028}, {396, 1908}, {636, 2028}, {396, 1788}},
			{{1980, 372}, {1980, 492}, {1980, 612}, {1860, 372}, {1740, 372}},
		},
		Respawns: [2][]Point{
			{{396, 1788}, {396, 1908}, {396, 2028}, {516, 2028}, {636, 2028}},
			{{1740, 372}, {1860, 372}, {1980, 372}, {1980, 492}, {1980, 612}},
		},
	},
	36: {
		Spawns: [2][]Point{
			{{372, 996}, {372, 900}, {372, 804}, {468, 948}, {468, 852}},
			{{2292, 756}, {2292, 852}, {2292, 948}, {2196, 900}, {2196, 804}},
		},
		Respawns: [2][]Point{
			{{372, 804}, {372, 900}, {372, 996}, {468, 948}, {468, 852}},
			{{2196, 804}, {2196, 900}, {2292, 948}, {2292, 852}, {2292, 756}},
		},
	},
	37: {
		Spawns: [2][]Point{
			{{180, 492}, {180, 588}, {180, 684}, {276, 540}, {276, 636}},
			{{1692, 492}, {1692, 588}, {1692, 684}, {1596, 636}, {1596, 540}},
		},
		Respawns: [2][]Point{
			{{276, 540}, {276, 636}, {180, 684}, {180, 588}, {180, 492}},
			{{1596, 540}, {1692, 492}, {1692, 588}, {1692, 684}, {1596, 636}},
		},
	},
	40: {
		Spawns: [2][]Point{
			{{156, 1524}, {252, 1524}, {348, 1524}, {156, 1428}, {156, 1332}},
			{{2028, 156}, {1932, 156}, {2028, 252}, {1836, 156}, {2028, 348}},
		},
		Respawns: [2][]Point{
			{{156, 1524}, {252, 1524}, {348, 1524}, {156, 1428}, {156, 1332}},
			{{2028, 156}, {2028, 252}, {2028, 348}, {1932, 156}, {1836, 156}},
		},
	},
	50: {
		Spawns: [2][]Point{
			{{252, 180}, {324, 180}, {180, 252}, {180, 324}, {396, 180}, {180, 396}},
			{{1980, 1548}, {1980, 1620}, {1908, 1692}, {1836, 1692}, {1980, 1476}, {1764, 1692}},
		},
		Respawns: [2][]Point{
			{{252, 180}, {180, 252}, {324, 180}, {180, 324}, {396, 180}},
			{{1980, 1620}, {1908, 1692}, {1980, 1548}, {1836, 1692}, {1980, 1476}},
		},
	},
	70: {
		Spawns: [2][]Point{
			{{492, 1764}, {588, 1764}, {684, 1764}, {420, 1764}, {492, 1692}},
			{{1740, 180}, {1644, 180}, {1548, 180}, {1740, 252}, {1812, 180}},
		},
		Respawns: [2][]Point{
			{{588, 1692}, {516, 1692}, {588, 1620}, {588, 1764}, {660, 1692}},
			{{1644, 252}, {1572, 252}, {1644, 180}, {1644, 324}, {1716, 252}},
		},
	},
	101: {
		Spawns: [2][]Point{
			{{444, 612}},
			{{780, 804}},
		},
		Respawns: [2][]Point{
			{{444, 612}},
			{{780, 804}},
		},
	},
	169: {
		Spawns: [2][]Point{
			{{156, 396}, {228, 396}, {300, 396}, {396, 324}, {396, 252}},
			{{2148, 1476}, {2076, 1476}, {2004, 1476}, {1932, 1620}, {1932, 1476}},
		},
		Respawns: [2][]Point{
			{{468, 180}, {468, 252}, {540, 180}, {396, 252}, {540, 252}},
			{{1860, 1716}, {1860, 1644}, {1788, 1716}, {1932, 1644}, {1788, 1644}},
		},
	},
	170: {
		Spawns: [2][]Point{
			{{276, 756}, {276, 828}, {276, 972}, {276, 1044}, {276, 684}},
			{{2700, 1068}, {2700, 924}, {2700, 852}, {2700, 1140}, {2700, 1212}},
		},
		Respawns: [2][]Point{
			{{492, 732}, {492, 660}, {492, 804}, {492, 588}, {492, 876}},
			{{2532, 1212}, {2532, 1284}, {2532, 1140}, {2532, 1356}, {2532, 1068}},
		},
	},
}
