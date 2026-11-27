package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"bangbang-server/game"
	"bangbang-server/handler"

	"github.com/gorilla/websocket"
)

const defaultDatabaseURL = "postgresql://bangbang_wy6y_user:0ANTGQ2sbtBOMn5e0HGcwjRhWyfxXp4I@dpg-dc43nrt9el5s73a4tl70-a.singapore-postgres.render.com/bangbang_wy6y"

var (
	addr      = flag.String("addr", ":8080", "HTTP listen address")
	staticDir = flag.String("static", "../server/public", "Path to server/public directory for static files")
	dbURL     = flag.String("db", "", "PostgreSQL database connection URL (or set DATABASE_URL env var)")
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  65536,
	WriteBufferSize: 65536,
	CheckOrigin:     func(r *http.Request) bool { return true },
}

func main() {
	flag.Parse()

	// Determine DB connection string
	activeDBURL := strings.TrimSpace(*dbURL)
	if activeDBURL == "" {
		activeDBURL = strings.TrimSpace(os.Getenv("DATABASE_URL"))
	}
	if activeDBURL == "" {
		activeDBURL = defaultDatabaseURL
	}

	var store *game.Store
	var err error

	log.Println("╔══════════════════════════════════════════╗")
	log.Println("║      🎮 BangBang Game Server v0.2       ║")
	log.Println("║                                         ║")
	log.Printf("║  HTTP + WebSocket on %s           ║\n", padRight(*addr, 12))
	log.Println("║  Auto-register: login = create account  ║")
	log.Println("║  Database: PostgreSQL (Render 30 days)  ║")
	log.Println("╚══════════════════════════════════════════╝")

	if activeDBURL != "" {
		log.Printf("[db] 🔌 Connecting to PostgreSQL...")
		store, err = game.NewStoreWithDB(activeDBURL)
		if err != nil {
			log.Printf("[db] ⚠️ Warning: DB connection failed: %v", err)
			log.Println("[db] ⚠️ Falling back to in-memory store.")
			store = game.NewStore()
		} else {
			defer store.Close()
			log.Println("[db] 🚀 Connected to PostgreSQL successfully!")
		}
	} else {
		store = game.NewStore()
		log.Println("[db] Running in-memory store only.")
	}

	mux := http.NewServeMux()

	// --- HTTP Auth API ---
	roomMgr := game.NewRoomManager()
	onlineMgr := game.NewOnlineTracker()
	broadcast := game.NewBroadcaster()
	authHandler := &handler.AuthHandler{Store: store}
	mux.Handle("/api/auth", authHandler)

	// --- Registration API (with captcha) ---
	regHandler := handler.NewRegisterHandler(store)
	mux.Handle("/api/register/", regHandler)
	mux.Handle("/api/register", regHandler)

	// --- Shop Catalog API ---
	catalogPath := "normal_shop_catalog.json"
	if _, err := os.Stat(catalogPath); err != nil {
		catalogPath = filepath.Join("..", "BangBang_Offline", "server", "normal_shop_catalog.json")
	}
	shopHandler := handler.NewShopHandler(catalogPath)
	mux.Handle("/goodsshopquery.php", shopHandler)
	mux.Handle("/cshopquery.php", shopHandler)

	// --- Observe Character Profile & Rank API ---
	observeHandler := handler.NewObserveHandler(store)
	mux.Handle("/observechar.php", observeHandler)
	mux.Handle("/ccharrankquery.php", observeHandler)
	mux.Handle("/ctoppowertanklist.php", observeHandler)

	// --- WebSocket endpoints ---
	mux.HandleFunc("/ws/login", func(w http.ResponseWriter, r *http.Request) {
		wsHandle(w, r, store, roomMgr, onlineMgr, broadcast, "login")
	})
	mux.HandleFunc("/ws/gate", func(w http.ResponseWriter, r *http.Request) {
		wsHandle(w, r, store, roomMgr, onlineMgr, broadcast, "gate")
	})
	mux.HandleFunc("/ws/comm", func(w http.ResponseWriter, r *http.Request) {
		wsHandle(w, r, store, roomMgr, onlineMgr, broadcast, "gate") // comm uses same handler
	})

	// --- Static file server for game assets ---
	absStatic, _ := filepath.Abs(*staticDir)
	log.Printf("[static] serving %s", absStatic)
	mux.Handle("/godot/", http.StripPrefix("/godot/", http.FileServer(http.Dir(filepath.Join(absStatic, "godot")))))
	mux.Handle("/", http.FileServer(http.Dir(absStatic)))

	// --- CORS middleware ---
	corsHandler := corsMiddleware(mux)

	log.Printf("🚀 Server starting on %s", *addr)
	if err := http.ListenAndServe(*addr, corsHandler); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

func wsHandle(w http.ResponseWriter, r *http.Request, store *game.Store, roomMgr *game.RoomManager, onlineMgr *game.OnlineTracker, broadcast *game.Broadcaster, role string) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("[%s] upgrade error: %v", role, err)
		return
	}

	log.Printf("[%s] new connection from %s", role, r.RemoteAddr)

	wsConn := handler.NewWSConn(conn, store, roomMgr, onlineMgr, broadcast, role)
	go wsConn.HandleLoop()
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, X-Client-Instance")
			w.Header().Set("Access-Control-Allow-Credentials", "true")
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		// Set cookie from auth responses
		if strings.HasPrefix(r.URL.Path, "/api/auth") {
			w.Header().Set("Vary", "Origin")
		}
		next.ServeHTTP(w, r)
	})
}

func padRight(s string, n int) string {
	if len(s) >= n {
		return s
	}
	return s + fmt.Sprintf("%*s", n-len(s), "")
}
