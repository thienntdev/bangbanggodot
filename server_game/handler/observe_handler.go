package handler

import (
	"encoding/json"
	"log"
	"net/http"

	"bangbang-server/game"
)

type ObserveHandler struct {
	Store *game.Store
}

func NewObserveHandler(store *game.Store) *ObserveHandler {
	return &ObserveHandler{Store: store}
}

func (h *ObserveHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "*")
	w.Header().Set("Content-Type", "application/json; charset=utf-8")

	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}

	q := r.URL.Query()
	identity := q.Get("charoid")
	if identity == "" {
		identity = q.Get("char")
	}

	char := h.Store.FindCharacterByIdentity(identity)
	if char == nil {
		log.Printf("[observe] ⚠️ Character not found for identity=%q", identity)
		resp := map[string]interface{}{
			"state":     0,
			"code":      404,
			"char_tank": []interface{}{},
			"msg":       "Không tìm thấy nhân vật.",
		}
		_ = json.NewEncoder(w).Encode(resp)
		return
	}

	log.Printf("[observe] 👤 Character profile requested: charID=%d, name=%s", char.CharID, char.Name)

	// Build tank list
	var charTanks []map[string]interface{}
	totalStars := 0
	for _, t := range char.Tanks {
		charTanks = append(charTanks, map[string]interface{}{
			"tank_tplt_id":    t.TankID,
			"level":           t.TankLevel,
			"external_id":     t.ExternalID,
			"halo_id":         t.HaloID,
			"skin_frame_type": 0,
			"proficiency_val": t.ProficiencyVal,
			"winmatchs":       t.WarCount,
			"totalkill":       t.WarCount * 3,
			"totalassist":     t.WarCount * 2,
			"fightScore":      int(t.TankLevel) * 200,
		})
		totalStars += int(t.TankLevel)
	}

	// Tech / Battle stats
	techBlock := map[string]interface{}{
		"totalmatchs":      10,
		"winmatchs":        8,
		"winpercent":       80,
		"escapeprecent":    0,
		"killerkingmatchs": 3,
		"assistkingmatchs": 4,
		"kda_count":        5,
		"destroyer_count":  2,
	}
	emptyBlock := map[string]interface{}{
		"totalmatchs":      0,
		"winmatchs":        0,
		"winpercent":       0,
		"escapeprecent":    0,
		"killerkingmatchs": 0,
		"assistkingmatchs": 0,
		"kda_count":        0,
		"destroyer_count":  0,
	}

	avID := char.AvatarID
	if avID == 0 {
		avID = 2801001
	}

	resp := map[string]interface{}{
		"state":               1,
		"code":                0,
		"displayId":           char.CharID,
		"char_oid":            char.CharID,
		"account_oid":         char.CharID,
		"account_id":          char.CharID,
		"char_uuid":           char.CharUuid,
		"char_name":           char.Name,
		"char_level":          char.Level,
		"char_avatar":         avID,
		"char_decorate":       0,
		"char_vippoint":       1000,
		"char_vip_time":       0,
		"char_super_vip_time": 0,
		"guild_id":            0,
		"guild_level":         0,
		"guild_name":          "",
		"team_id":             0,
		"team_level":          0,
		"team_name":           "",
		"military_star":       totalStars,
		"char_tank":           charTanks,
		"char_tech": map[string]interface{}{
			"total":     techBlock,
			"pvp":       techBlock,
			"league":    emptyBlock,
			"ladderpvp": emptyBlock,
		},
	}

	_ = json.NewEncoder(w).Encode(resp)
}
