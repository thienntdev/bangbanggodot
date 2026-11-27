package handler

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"bytes"
	"log"
	"math/big"
	mrand "math/rand"
	"net/http"
	"strings"
	"sync"
	"time"

	"bangbang-server/game"
)

// CaptchaEntry stores a generated captcha.
type CaptchaEntry struct {
	Code      string
	CreatedAt time.Time
}

// RegisterHandler handles all /api/register/* endpoints.
type RegisterHandler struct {
	Store    *game.Store
	mu       sync.RWMutex
	captchas map[string]*CaptchaEntry // captchaId → entry
}

func NewRegisterHandler(store *game.Store) *RegisterHandler {
	h := &RegisterHandler{
		Store:    store,
		captchas: make(map[string]*CaptchaEntry),
	}
	// Cleanup expired captchas every 5 minutes
	go func() {
		for {
			time.Sleep(5 * time.Minute)
			h.cleanup()
		}
	}()
	return h
}

func (h *RegisterHandler) cleanup() {
	h.mu.Lock()
	defer h.mu.Unlock()
	now := time.Now()
	for id, entry := range h.captchas {
		if now.Sub(entry.CreatedAt) > 5*time.Minute {
			delete(h.captchas, id)
		}
	}
}

func (h *RegisterHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/register")
	if path == "" || path == "/" {
		h.handleRegister(w, r)
		return
	}

	switch path {
	case "/captcha":
		h.handleCaptcha(w, r)
	case "/status":
		h.handleStatus(w, r)
	case "/email-code":
		h.handleEmailCode(w, r)
	case "/quiz":
		h.handleQuiz(w, r)
	case "/quiz-check":
		h.handleQuizCheck(w, r)
	case "/quiz-rooms":
		h.handleQuizRooms(w, r)
	default:
		http.NotFound(w, r)
	}
}

// --- GET /api/register/status ---
func (h *RegisterHandler) handleStatus(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"ok":    true,
		"state": "open",
		"left":  100,
		"cap":   100,
		"quiz":  false,
		"regcode": false,
	})
}

// --- GET /api/register/captcha ---
func (h *RegisterHandler) handleCaptcha(w http.ResponseWriter, r *http.Request) {
	code := randomDigits(4)
	captchaID := randomHex(16)

	h.mu.Lock()
	h.captchas[captchaID] = &CaptchaEntry{
		Code:      code,
		CreatedAt: time.Now(),
	}
	h.mu.Unlock()

	img := generateCaptchaImage(code, 200, 70)

	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]interface{}{
			"ok": false, "error": "Lỗi tạo captcha.", "code": "SERVER",
		})
		return
	}

	pngB64 := base64.StdEncoding.EncodeToString(buf.Bytes())

	log.Printf("[register] captcha created: id=%s code=%s", captchaID, code)

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"ok":    true,
		"id":    captchaID,
		"png":   pngB64,
		"email": false,
		"quiz":  false,
		"regcode": false,
	})
}

// --- POST /api/register/email-code (stub) ---
func (h *RegisterHandler) handleEmailCode(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"ok":     true,
		"to":     "dev@bangbang.local",
		"ttl":    600,
		"resend": 0,
	})
}

// --- POST /api/register/quiz-rooms (stub) ---
func (h *RegisterHandler) handleQuizRooms(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"ok":    false,
		"error": "Quiz không bắt buộc.",
		"code":  "DISABLED",
	})
}

// --- POST /api/register/quiz (stub) ---
func (h *RegisterHandler) handleQuiz(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"ok":    false,
		"error": "Quiz không bắt buộc.",
		"code":  "DISABLED",
	})
}

// --- POST /api/register/quiz-check (stub) ---
func (h *RegisterHandler) handleQuizCheck(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"ok":    true,
		"pass":  true,
		"score": 10,
		"need":  1,
		"total": 1,
		"token": randomHex(32),
	})
}

// --- POST /api/register ---
func (h *RegisterHandler) handleRegister(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		Username  string `json:"username"`
		Password  string `json:"password"`
		CaptchaID string `json:"captchaId"`
		Captcha   string `json:"captcha"`
		QuizToken string `json:"quizToken"`
		RegCode   string `json:"regCode"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]interface{}{
			"ok": false, "error": "Dữ liệu không hợp lệ.", "code": "PARSE",
		})
		return
	}

	// Validate username
	req.Username = strings.TrimSpace(req.Username)
	if len(req.Username) < 3 || len(req.Username) > 20 {
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"ok": false, "error": "Tên đăng nhập phải từ 3-20 ký tự.", "code": "USERNAME",
		})
		return
	}

	// Validate password
	if len(req.Password) < 4 || len(req.Password) > 32 {
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"ok": false, "error": "Mật khẩu phải từ 4-32 ký tự.", "code": "PASSWORD",
		})
		return
	}

	// Verify captcha
	h.mu.Lock()
	entry, exists := h.captchas[req.CaptchaID]
	if exists {
		delete(h.captchas, req.CaptchaID) // one-time use
	}
	h.mu.Unlock()

	if !exists || time.Since(entry.CreatedAt) > 5*time.Minute {
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"ok": false, "error": "Captcha hết hạn, hãy tải lại.", "code": "CAPTCHA", "renew": true,
		})
		return
	}

	if !strings.EqualFold(entry.Code, strings.TrimSpace(req.Captcha)) {
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"ok": false, "error": "Mã captcha không đúng.", "code": "CAPTCHA", "renew": true,
		})
		return
	}

	// Check if username already exists
	if h.Store.GetUser(req.Username) != nil {
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"ok": false, "error": "Tên đăng nhập đã tồn tại.", "code": "DUPLICATE", "renew": true,
		})
		return
	}

	// Register
	char, err := h.Store.Register(req.Username, req.Password)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"ok": false, "error": err.Error(), "code": "REGISTER", "renew": true,
		})
		return
	}

	log.Printf("[register] account created: user=%s charID=%d", char.Name, char.CharID)

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"ok":       true,
		"username": char.Name,
	})
}

// ========== Captcha Image Generator ==========

// Font: simple 5x7 pixel font for uppercase letters and digits.
var pixelFont = map[rune][]string{
	'0': {"01110", "10011", "10101", "10101", "10101", "11001", "01110"},
	'1': {"00100", "01100", "10100", "00100", "00100", "00100", "11111"},
	'2': {"01110", "10001", "00001", "00110", "01000", "10000", "11111"},
	'3': {"01110", "10001", "00001", "00110", "00001", "10001", "01110"},
	'4': {"00010", "00110", "01010", "10010", "11111", "00010", "00010"},
	'5': {"11111", "10000", "11110", "00001", "00001", "10001", "01110"},
	'6': {"01110", "10000", "10000", "11110", "10001", "10001", "01110"},
	'7': {"11111", "00001", "00010", "00100", "01000", "01000", "01000"},
	'8': {"01110", "10001", "10001", "01110", "10001", "10001", "01110"},
	'9': {"01110", "10001", "10001", "01111", "00001", "00001", "01110"},
}

func generateCaptchaImage(code string, width, height int) image.Image {
	img := image.NewRGBA(image.Rect(0, 0, width, height))

	// Background: dark gradient
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			r := uint8(25 + mrand.Intn(15))
			g := uint8(30 + mrand.Intn(15))
			b := uint8(45 + mrand.Intn(15))
			img.Set(x, y, color.RGBA{r, g, b, 255})
		}
	}

	// Noise dots
	for i := 0; i < width*height/8; i++ {
		x := mrand.Intn(width)
		y := mrand.Intn(height)
		c := uint8(60 + mrand.Intn(80))
		img.Set(x, y, color.RGBA{c, c, c, 255})
	}

	// Noise lines
	for i := 0; i < 4; i++ {
		x1 := mrand.Intn(width)
		y1 := mrand.Intn(height)
		x2 := mrand.Intn(width)
		y2 := mrand.Intn(height)
		lineColor := color.RGBA{
			uint8(40 + mrand.Intn(60)),
			uint8(50 + mrand.Intn(60)),
			uint8(70 + mrand.Intn(60)),
			255,
		}
		drawLine(img, x1, y1, x2, y2, lineColor)
	}

	// Draw each character with scale and random offset
	scale := 4
	charWidth := 5 * scale
	totalWidth := len(code) * (charWidth + scale)
	startX := (width - totalWidth) / 2
	startY := (height - 7*scale) / 2

	colors := []color.RGBA{
		{255, 120, 80, 255},   // orange
		{80, 220, 120, 255},   // green
		{100, 180, 255, 255},  // blue
		{255, 220, 80, 255},   // yellow
		{220, 130, 255, 255},  // purple
		{255, 100, 150, 255},  // pink
		{80, 255, 220, 255},   // cyan
	}

	for i, ch := range code {
		glyph, ok := pixelFont[ch]
		if !ok {
			continue
		}

		charColor := colors[i%len(colors)]
		offsetY := mrand.Intn(10) - 5
		offsetX := mrand.Intn(6) - 3

		for row := 0; row < 7; row++ {
			for col := 0; col < 5; col++ {
				if glyph[row][col] == '1' {
					px := startX + i*(charWidth+scale) + col*scale + offsetX
					py := startY + row*scale + offsetY
					// Draw scaled pixel with slight variation
					for dy := 0; dy < scale; dy++ {
						for dx := 0; dx < scale; dx++ {
							if px+dx >= 0 && px+dx < width && py+dy >= 0 && py+dy < height {
								// Add slight color variation for anti-alias look
								cr := clampU8(int(charColor.R) + mrand.Intn(30) - 15)
								cg := clampU8(int(charColor.G) + mrand.Intn(30) - 15)
								cb := clampU8(int(charColor.B) + mrand.Intn(30) - 15)
								img.Set(px+dx, py+dy, color.RGBA{cr, cg, cb, 255})
							}
						}
					}
				}
			}
		}
	}

	// More noise on top
	for i := 0; i < width*height/12; i++ {
		x := mrand.Intn(width)
		y := mrand.Intn(height)
		c := uint8(50 + mrand.Intn(60))
		img.Set(x, y, color.RGBA{c, c, c, 120})
	}

	return img
}

func drawLine(img *image.RGBA, x1, y1, x2, y2 int, c color.RGBA) {
	dx := abs(x2 - x1)
	dy := abs(y2 - y1)
	sx, sy := 1, 1
	if x1 > x2 { sx = -1 }
	if y1 > y2 { sy = -1 }
	err := dx - dy

	for {
		if x1 >= 0 && x1 < img.Rect.Max.X && y1 >= 0 && y1 < img.Rect.Max.Y {
			img.Set(x1, y1, c)
			// Thicker line
			if x1+1 < img.Rect.Max.X {
				img.Set(x1+1, y1, c)
			}
		}
		if x1 == x2 && y1 == y2 { break }
		e2 := 2 * err
		if e2 > -dy { err -= dy; x1 += sx }
		if e2 < dx { err += dx; y1 += sy }
	}
}

func abs(x int) int {
	if x < 0 { return -x }
	return x
}

func clampU8(v int) uint8 {
	if v < 0 { return 0 }
	if v > 255 { return 255 }
	return uint8(v)
}

// randomDigits generates a random numeric string of given length.
func randomDigits(length int) string {
	result := make([]byte, length)
	for i := range result {
		n, _ := rand.Int(rand.Reader, big.NewInt(10))
		result[i] = '0' + byte(n.Int64())
	}
	return string(result)
}

func randomHex(length int) string {
	b := make([]byte, length/2)
	rand.Read(b)
	return fmt.Sprintf("%x", b)
}
