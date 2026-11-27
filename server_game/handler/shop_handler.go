package handler

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

type CatalogPayment struct {
	Key      string `json:"key"`
	CoinType int    `json:"coinType"` // 1: Xu, 2: Bạc, 3: Xu Khóa
	Price    int    `json:"price"`
	Quantity int    `json:"quantity"`
}

type CatalogOffer struct {
	GoodsID       int              `json:"goodsId"`
	ItemID        int              `json:"itemId"`
	Tab           int              `json:"tab"` // 1: Đề cử, 2: Tank, 7: Skin, 4: VP, 5: NL, 6: Trợ thủ
	GrantKind     string           `json:"grantKind"`
	Name          string           `json:"name"`
	Description   string           `json:"description"`
	ContainerType int              `json:"containerType"`
	MaxCount      int              `json:"maxCount"`
	Payments      []CatalogPayment `json:"payments"`
	CanUseGift    bool             `json:"canUseGift"`
	AutoUse       bool             `json:"autoUse"`
	Available     bool             `json:"available"`
}

type ShopCatalog struct {
	Offers []CatalogOffer `json:"offers"`
}

type ShopHandler struct {
	catalog ShopCatalog
}

func NewShopHandler(catalogPath string) *ShopHandler {
	h := &ShopHandler{}
	data, err := os.ReadFile(catalogPath)
	if err != nil {
		log.Printf("[shop] ⚠️ Failed to read %s: %v", catalogPath, err)
		return h
	}
	if err := json.Unmarshal(data, &h.catalog); err != nil {
		log.Printf("[shop] ⚠️ Failed to parse shop catalog JSON: %v", err)
		return h
	}

	// Bổ sung các vật phẩm thời trang (tab 3) và trang trí (tab 9)
	avatars := []int{2801010, 2801123, 990030114, 990030117, 990030120}
	for _, av := range avatars {
		h.catalog.Offers = append(h.catalog.Offers, CatalogOffer{
			GoodsID:       70000000 + av,
			ItemID:        av,
			Tab:           3,
			GrantKind:     "item",
			Name:          "Thời trang",
			ContainerType: 4,
			MaxCount:      1,
			Payments: []CatalogPayment{
				{Key: "primary", CoinType: 2, Price: 100, Quantity: 1}, // 100 Bạc
			},
			Available: true,
		})
	}

	decors := []int{990020026, 990030109, 990030111}
	for _, dec := range decors {
		h.catalog.Offers = append(h.catalog.Offers, CatalogOffer{
			GoodsID:       70000000 + dec,
			ItemID:        dec,
			Tab:           9,
			GrantKind:     "item",
			Name:          "Trang trí",
			ContainerType: 7,
			MaxCount:      1,
			Payments: []CatalogPayment{
				{Key: "primary", CoinType: 2, Price: 100, Quantity: 1}, // 100 Bạc
			},
			Available: true,
		})
	}

	for _, o := range h.catalog.Offers {
		globalCatalogOffers[uint32(o.GoodsID)] = o
	}

	log.Printf("[shop] 🛒 Loaded %d shop offers from catalog", len(h.catalog.Offers))
	return h
}

var globalCatalogOffers = make(map[uint32]CatalogOffer)

func GetShopOffer(goodsID uint32) *CatalogOffer {
	if o, ok := globalCatalogOffers[goodsID]; ok {
		return &o
	}
	return nil
}

func (h *ShopHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "*")
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}

	q := r.URL.Query()
	gt, _ := strconv.Atoi(q.Get("gt"))
	st, _ := strconv.Atoi(q.Get("st"))
	page, _ := strconv.Atoi(q.Get("p"))
	size, _ := strconv.Atoi(q.Get("r"))
	if size <= 0 {
		size = 10000
	}
	if gt == 0 {
		gt = 1
	}

	// Lọc mặt hàng theo Tab (gt)
	var filtered []CatalogOffer
	for _, o := range h.catalog.Offers {
		if !o.Available {
			continue
		}
		if o.Tab != gt {
			continue
		}
		if st == 100 { // Lọc chỉ đồ mua bằng Xu Khóa (coinType == 3)
			hasBound := false
			for _, p := range o.Payments {
				if p.CoinType == 3 {
					hasBound = true
					break
				}
			}
			if !hasBound {
				continue
			}
		}
		filtered = append(filtered, o)
	}

	total := len(filtered)
	log.Printf("[shop] 🛒 Query gt=%d st=%d (page=%d, size=%d) -> returning %d offers", gt, st, page, size, total)
	start := page * size
	if start > total {
		start = total
	}
	end := start + size
	if end > total {
		end = total
	}
	paged := filtered[start:end]

	var sb strings.Builder
	sb.WriteString("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n")
	sb.WriteString(fmt.Sprintf("<query amount=\"%d\" cur_time=\"%d\">\n", total, time.Now().Unix()))

	for _, o := range paged {
		goodsType := o.Tab
		if o.Tab == 2 {
			goodsType = 2 // Tank
		} else if o.Tab == 7 {
			goodsType = 6 // Skin (KINDS[6] == "Skin")
		} else if o.Tab == 3 {
			goodsType = 3 // Thời trang
		} else if o.Tab == 9 {
			goodsType = 8 // Trang trí (KINDS[8] == "Trang trí")
		} else if o.Tab == 4 {
			goodsType = 4 // Vật phẩm
		} else if o.Tab == 5 {
			goodsType = 5 // Nguyên liệu
		} else if o.Tab == 6 {
			goodsType = 5 // Trợ thủ container
		} else if o.Tab == 1 {
			if o.GrantKind == "tank" {
				goodsType = 2
			} else {
				goodsType = 4
			}
		}

		coinType1 := 1
		price1 := 0
		cnt1 := 1
		coinType2 := 0
		price2_1 := 0

		if len(o.Payments) > 0 {
			coinType1 = o.Payments[0].CoinType
			price1 = o.Payments[0].Price
			if o.Payments[0].Quantity > 0 {
				cnt1 = o.Payments[0].Quantity
			}
		}
		if len(o.Payments) > 1 {
			coinType2 = o.Payments[1].CoinType
			price2_1 = o.Payments[1].Price
		}

		canGift := 0
		if o.CanUseGift {
			canGift = 1
		}

		sb.WriteString(fmt.Sprintf(
			`  <row goods_id="%d" template_oid="%d" goods_type="%d" first_label="%d" second_label="1" `+
				`coin_type="%d" coin_type2="%d" price1="%d" price2_1="%d" count_1="%d" count_2="0" count_3="0" `+
				`price2="0" price3="0" price2_2="0" price2_3="0" agio_price1="0" agio_price2="0" agio_price3="0" `+
				`agio_price2_1="0" agio_price2_2="0" agio_price2_3="0" is_agio="0" is_hot="1" is_new="0" `+
				`limit_level="0" vip_level="0" can_use_gift="%d" is_limit_count="0" char_limit_count="0" is_limit_time="0"/>`+"\n",
			o.GoodsID, o.ItemID, goodsType, o.Tab,
			coinType1, coinType2, price1, price2_1, cnt1,
			canGift,
		))
	}

	sb.WriteString("</query>")

	w.Header().Set("Content-Type", "application/xml; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(sb.String()))
}
