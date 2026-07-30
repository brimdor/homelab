# Pair a Moonlight Client

A new Moonlight client must be paired once with the Wolf host. After
pairing, the client remembers the host and can connect without
re-pairing (until Wolf's keypair is rotated).

## Prerequisites

- A Moonlight client installed
- Tailscale installed and joined to the homelab tailnet (`tail18136a.ts.net`)

## Steps

1. **Open the Moonlight client.**

2. **Add the host manually.** In Moonlight's UI, choose
   *Add PC manually* (or *Pair new host* on some clients) and enter
   one of:
   - `wolf.tail18136a.ts.net` — for tailnet devices (recommended for non-LAN)
   - `10.0.20.19` — for homelab LAN devices (no Tailscale required for this path)

3. **Moonlight shows a 4-digit PIN.** Note it.

4. **Open the Wolf pairing page** in a browser (anywhere — LAN,
   Tailscale, or the cloudflared tunnel):
   - From anywhere: <https://wolf.eaglepass.io/pin/>
   - From the homelab LAN directly: <http://10.0.20.19:47989/pin/>

5. **Enter the PIN** in the Wolf page. Click *Pair*.

6. **Return to Moonlight.** The host now appears in the host list.
   Click it.

7. **Accept the default app list** in Moonlight. You should see at
   least:
   - **Wolf UI** — the in-streaming profile/app launcher
   - **Steam** — Steam Big Picture in a containerized Sway session
   - **Desktop** — fallback Xfce desktop for non-Steam apps

## Permission management

The first client paired is automatically granted **full permissions**
(Launch Apps, Mouse Input, Keyboard Input, etc.). Subsequent clients
get *View Streams* and *List Apps* only by default. To grant more
permissions:

1. In a paired Moonlight client, launch the **Wolf UI** app.
2. Open the *Permissions* tab.
3. Find the newly paired client.
4. Toggle the permissions you want to grant.

Or, from the Wolf pairing page:
1. Click the *Settings* icon.
2. Find the client.
3. Edit its permissions.

## Tailscale ACLs

If the Moonlight client connects via `wolf.tail18136a.ts.net`, the
Tailscale ACLs must permit the client's source (e.g. `group:family`
or a specific user) to reach the `tag:k8s-homelab` tag on the
streaming ports. See `platform/tailscale/README.md` for the ACL
configuration. The WebUI (TCP 47989) is permitted separately.

If the client cannot connect and `tailscale status` shows
`connection denied`, the ACL is the cause. Fix the ACL in the
Tailscale admin console, not on the homelab.

## Rotating the keypair

If you want to force re-pairing of all clients (e.g. after a
security incident), delete the `key.pem` and `cert.pem` files in
the `/etc/wolf` PVC (path on the NFS share:
`/mnt/user/heartlib/<pvc-uuid>/key.pem` and `cert.pem`) and
restart the Wolf pod. Wolf will generate a new keypair on next
startup, and all clients will need to re-pair.
