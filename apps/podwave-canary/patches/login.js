import { j as json } from './index-wpIsICWW.js';
import bcrypt from 'bcryptjs';
import { randomUUID } from 'crypto';
import { g as getDb } from './index2-CdX4GARg.js';
import 'better-sqlite3';
import 'fs';
import 'url';
import 'path';

async function POST({ request }) {
  try {
    const data = await request.json();
    const { username, password } = data;
    if (!username || !password) return json({ error: "Missing fields" }, { status: 400 });
    const db = getDb();
    const user = db.prepare("SELECT * FROM users WHERE username = ?").get(username);
    if (!user || !bcrypt.compareSync(password, user.password_hash)) {
      return json({ error: "Invalid credentials" }, { status: 401 });
    }
    const sessionId = randomUUID();
    const expiresAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1e3).toISOString();
    db.prepare("INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)").run(sessionId, user.id, expiresAt);
    return json(
      { userId: user.id, name: user.name, username: user.username, isAdmin: !!user.is_admin },
      { headers: { "Set-Cookie": `podwave_session=${sessionId}; HttpOnly; SameSite=Lax; Secure; Path=/; Max-Age=${30 * 24 * 60 * 60}` } }
    );
  } catch (err) {
    console.error("Login error:", err);
    return json({ error: "Server error" }, { status: 500 });
  }
}

export { POST };
//# sourceMappingURL=_server-B0v96ZDY.js.map
