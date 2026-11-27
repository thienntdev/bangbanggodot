package handler

import (
	"encoding/json"
	"log"
	"net/http"

	"bangbang-server/game"

	"github.com/google/uuid"
)

// AuthHandler handles POST /api/auth for HTTP-based login.
type AuthHandler struct {
	Store *game.Store
}

type authRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
	Key      string `json:"key,omitempty"`
	Resume   string `json:"resume,omitempty"`
}

type authResponse struct {
	OK          bool                   `json:"ok"`
	Error       string                 `json:"error,omitempty"`
	Code        string                 `json:"code,omitempty"`
	AuthToken   string                 `json:"authToken,omitempty"`
	Account     map[string]interface{} `json:"account,omitempty"`
	ResumeToken string                 `json:"resumeToken,omitempty"`
}

func (h *AuthHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req authRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, authResponse{
			OK:    false,
			Error: "Dữ liệu đăng nhập không hợp lệ.",
			Code:  "PARSE",
		})
		return
	}

	if req.Username == "" || req.Password == "" {
		writeJSON(w, http.StatusBadRequest, authResponse{
			OK:    false,
			Error: "Tên đăng nhập và mật khẩu không được để trống.",
			Code:  "MISSING",
		})
		return
	}

	log.Printf("[auth] login attempt: user=%s", req.Username)

	// Auto-register or authenticate
	char, err := h.Store.Register(req.Username, req.Password)
	if err != nil {
		writeJSON(w, http.StatusOK, authResponse{
			OK:    false,
			Error: err.Error(),
			Code:  "AUTH",
		})
		return
	}

	authToken := uuid.New().String()
	resumeToken := uuid.New().String()

	log.Printf("[auth] login success: user=%s charID=%d", char.Name, char.CharID)

	writeJSON(w, http.StatusOK, authResponse{
		OK:        true,
		AuthToken: authToken,
		Account: map[string]interface{}{
			"username": char.Name,
			"name":     char.Name,
		},
		ResumeToken: resumeToken,
	})
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
