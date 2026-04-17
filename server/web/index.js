"use strict";

const path = require("path");
const fs = require("fs");
const express = require("express");
const cors = require("cors");
const bcrypt = require("bcrypt");
const jwt = require("jsonwebtoken");
const Database = require("better-sqlite3");
require("dotenv").config({ path: path.join(__dirname, ".env") });

const PORT = Number(process.env.PORT) || 5050;
const JWT_SECRET = process.env.JWT_SECRET || "dev-only-change-me";
const ROOT = path.join(__dirname, "../../ui/web");
const DATA_DIR = path.join(__dirname, "data");
const DB_PATH = path.join(DATA_DIR, "buffet.db");

if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

const db = new Database(DB_PATH);
db.pragma("journal_mode = WAL");

db.exec(`
CREATE TABLE IF NOT EXISTS places (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  location TEXT,
  detail TEXT,
  status TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS menu_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  icon TEXT,
  description TEXT,
  location TEXT,
  sort_order INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_credentials (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  username TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
`);

function seedIfEmpty() {
  const adminRow = db.prepare("SELECT username FROM admin_credentials WHERE id = 1").get();
  if (!adminRow) {
    const hash = bcrypt.hashSync("1234", 10);
    const now = new Date().toISOString();
    db.prepare(
      "INSERT INTO admin_credentials (id, username, password_hash, updated_at) VALUES (1, ?, ?, ?)"
    ).run("admin", hash, now);
  }

  const placeCount = db.prepare("SELECT COUNT(*) AS c FROM places").get().c;
  if (placeCount === 0) {
    const now = new Date().toISOString();
    const insert = db.prepare(
      `INSERT INTO places (name, category, location, detail, status, updated_at)
       VALUES (@name, @category, @location, @detail, @status, @updated_at)`
    );
    const defaults = [
      { name: "남자 화장실", category: "toilet", location: "입구 우측 복도", detail: "1층 위치, 장애인 화장실 포함", status: "active" },
      { name: "여자 화장실", category: "toilet", location: "입구 좌측 복도", detail: "1층 위치", status: "active" },
      { name: "스테이크 진열대", category: "menu", location: "A구역 중앙", detail: "당일 구운 스테이크 제공, 오후 6시 이후 추가", status: "active" },
      { name: "샐러드 바", category: "menu", location: "B구역 입구", detail: "생야채·드레싱 구비", status: "active" },
      { name: "음료 코너", category: "facility", location: "계산대 옆", detail: "탄산·주스·물 셀프 제공", status: "active" }
    ];
    for (const p of defaults) insert.run({ ...p, updated_at: now });
  }

  const menuCount = db.prepare("SELECT COUNT(*) AS c FROM menu_items").get().c;
  if (menuCount === 0) {
    const now = new Date().toISOString();
    const insert = db.prepare(
      `INSERT INTO menu_items (name, icon, description, location, sort_order, updated_at)
       VALUES (@name, @icon, @description, @location, @sort_order, @updated_at)`
    );
    const items = [
      { name: "스테이크", icon: "🥩", description: "당일 구운 프리미엄 스테이크", location: "A구역 3번 진열대", sort_order: 1 },
      { name: "샐러드", icon: "🥗", description: "신선한 채소 샐러드", location: "B구역 1번 진열대", sort_order: 2 },
      { name: "초밥", icon: "🍣", description: "당일 제조 초밥", location: "C구역 2번 진열대", sort_order: 3 },
      { name: "음료수", icon: "🥤", description: "탄산·주스·물", location: "음료 코너", sort_order: 4 }
    ];
    for (const m of items) insert.run({ ...m, updated_at: now });
  }
}

function ensureTablePlaces() {
  const exists = db.prepare("SELECT 1 FROM places WHERE name = ? LIMIT 1");
  const insert = db.prepare(
    `INSERT INTO places (name, category, location, detail, status, updated_at)
     VALUES (?, 'other', ?, ?, 'active', ?)`
  );
  const now = new Date().toISOString();
  const location = "매장 좌석";
  const detail = "QR·요청 시 테이블 번호 참조";
  for (let n = 1; n <= 9; n++) {
    const name = `테이블 ${n}번`;
    if (exists.get(name)) continue;
    insert.run(name, location, detail, now);
  }
}

seedIfEmpty();
ensureTablePlaces();

const app = express();
app.use(cors({ origin: true, credentials: true }));
app.use(express.json({ limit: "1mb" }));

function rowToPlace(row) {
  return {
    id: row.id,
    name: row.name,
    category: row.category,
    location: row.location || "",
    detail: row.detail || "",
    status: row.status
  };
}

function rowToMenuItem(row) {
  return {
    id: row.id,
    name: row.name,
    icon: row.icon || "🍽️",
    desc: row.description || "",
    location: row.location || "",
    order: row.sort_order
  };
}

function authMiddleware(req, res, next) {
  const h = req.headers.authorization;
  if (!h || !h.startsWith("Bearer ")) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  try {
    const payload = jwt.verify(h.slice(7), JWT_SECRET);
    req.adminUsername = payload.sub;
    next();
  } catch {
    return res.status(401).json({ error: "Unauthorized" });
  }
}

app.post("/api/auth/login", (req, res) => {
  const id = (req.body && req.body.id) || "";
  const pw = (req.body && req.body.pw) || "";
  const row = db.prepare("SELECT username, password_hash FROM admin_credentials WHERE id = 1").get();
  if (!row || id !== row.username) {
    return res.status(401).json({ error: "Invalid credentials" });
  }
  if (!bcrypt.compareSync(pw, row.password_hash)) {
    return res.status(401).json({ error: "Invalid credentials" });
  }
  const token = jwt.sign({ sub: row.username }, JWT_SECRET, { expiresIn: "7d" });
  return res.json({ token });
});

app.get("/api/admin/me", authMiddleware, (req, res) => {
  res.json({ username: req.adminUsername });
});

app.patch("/api/admin/settings", authMiddleware, (req, res) => {
  const { username, password } = req.body || {};
  const row = db.prepare("SELECT username FROM admin_credentials WHERE id = 1").get();
  if (!row) return res.status(500).json({ error: "Admin not configured" });

  let newUsername = row.username;
  if (username != null && String(username).trim()) {
    newUsername = String(username).trim();
  }
  let newHash = db.prepare("SELECT password_hash FROM admin_credentials WHERE id = 1").get().password_hash;
  if (password != null && String(password).length > 0) {
    newHash = bcrypt.hashSync(String(password), 10);
  }

  const now = new Date().toISOString();
  db.prepare(
    "UPDATE admin_credentials SET username = ?, password_hash = ?, updated_at = ? WHERE id = 1"
  ).run(newUsername, newHash, now);

  const token = jwt.sign({ sub: newUsername }, JWT_SECRET, { expiresIn: "7d" });
  res.json({ ok: true, token, username: newUsername });
});

app.get("/api/places", authMiddleware, (req, res) => {
  const rows = db.prepare("SELECT * FROM places ORDER BY id ASC").all();
  res.json(rows.map(rowToPlace));
});

app.post("/api/places", authMiddleware, (req, res) => {
  const { name, category, location, detail, status } = req.body || {};
  if (!name || !String(name).trim()) return res.status(400).json({ error: "name required" });
  if (!category) return res.status(400).json({ error: "category required" });
  const now = new Date().toISOString();
  const info = db
    .prepare(
      `INSERT INTO places (name, category, location, detail, status, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)`
    )
    .run(
      String(name).trim(),
      String(category),
      location != null ? String(location) : "",
      detail != null ? String(detail) : "",
      status || "active",
      now
    );
  const row = db.prepare("SELECT * FROM places WHERE id = ?").get(info.lastInsertRowid);
  res.status(201).json(rowToPlace(row));
});

app.put("/api/places/:id", authMiddleware, (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) return res.status(400).json({ error: "invalid id" });
  const existing = db.prepare("SELECT * FROM places WHERE id = ?").get(id);
  if (!existing) return res.status(404).json({ error: "not found" });
  const { name, category, location, detail, status } = req.body || {};
  const now = new Date().toISOString();
  db.prepare(
    `UPDATE places SET name = ?, category = ?, location = ?, detail = ?, status = ?, updated_at = ?
     WHERE id = ?`
  ).run(
    name != null ? String(name).trim() : existing.name,
    category != null ? String(category) : existing.category,
    location != null ? String(location) : existing.location,
    detail != null ? String(detail) : existing.detail,
    status != null ? String(status) : existing.status,
    now,
    id
  );
  const row = db.prepare("SELECT * FROM places WHERE id = ?").get(id);
  res.json(rowToPlace(row));
});

app.delete("/api/places/:id", authMiddleware, (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) return res.status(400).json({ error: "invalid id" });
  const info = db.prepare("DELETE FROM places WHERE id = ?").run(id);
  if (info.changes === 0) return res.status(404).json({ error: "not found" });
  res.status(204).end();
});

app.get("/api/menu-items", authMiddleware, (req, res) => {
  const rows = db.prepare("SELECT * FROM menu_items ORDER BY sort_order ASC, id ASC").all();
  res.json(rows.map(rowToMenuItem));
});

app.post("/api/menu-items", authMiddleware, (req, res) => {
  const { name, icon, desc, location, order } = req.body || {};
  if (!name || !String(name).trim()) return res.status(400).json({ error: "name required" });
  const now = new Date().toISOString();
  const sortOrder = order != null ? Number(order) || 1 : 1;
  const info = db
    .prepare(
      `INSERT INTO menu_items (name, icon, description, location, sort_order, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)`
    )
    .run(
      String(name).trim(),
      icon != null ? String(icon) : "🍽️",
      desc != null ? String(desc) : "",
      location != null ? String(location) : "",
      sortOrder,
      now
    );
  const row = db.prepare("SELECT * FROM menu_items WHERE id = ?").get(info.lastInsertRowid);
  res.status(201).json(rowToMenuItem(row));
});

app.put("/api/menu-items/:id", authMiddleware, (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) return res.status(400).json({ error: "invalid id" });
  const existing = db.prepare("SELECT * FROM menu_items WHERE id = ?").get(id);
  if (!existing) return res.status(404).json({ error: "not found" });
  const { name, icon, desc, location, order } = req.body || {};
  const now = new Date().toISOString();
  const sortOrder = order != null ? Number(order) || existing.sort_order : existing.sort_order;
  db.prepare(
    `UPDATE menu_items SET name = ?, icon = ?, description = ?, location = ?, sort_order = ?, updated_at = ?
     WHERE id = ?`
  ).run(
    name != null ? String(name).trim() : existing.name,
    icon != null ? String(icon) : existing.icon,
    desc != null ? String(desc) : existing.description,
    location != null ? String(location) : existing.location,
    sortOrder,
    now,
    id
  );
  const row = db.prepare("SELECT * FROM menu_items WHERE id = ?").get(id);
  res.json(rowToMenuItem(row));
});

app.delete("/api/menu-items/:id", authMiddleware, (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) return res.status(400).json({ error: "invalid id" });
  const info = db.prepare("DELETE FROM menu_items WHERE id = ?").run(id);
  if (info.changes === 0) return res.status(404).json({ error: "not found" });
  res.status(204).end();
});

app.use("/ui", express.static(ROOT, { extensions: ["html"] }));

app.listen(PORT, () => {
  console.log(`Buffet control server listening on http://localhost:${PORT}`);
  console.log(`SQLite: ${DB_PATH}`);
  console.log(`Open admin UI: http://localhost:${PORT}/ui/buffet_admin_ui/buffet_admin.html`);
});
