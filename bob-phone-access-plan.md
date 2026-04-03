# BOB — Smartphone Access Build Plan
### *Talk to BOB from your phone · at home · away from home*

---

## What We're Building

Two access modes depending on where Rob is:

**On the home network** — phone connects directly to the dashboard at `192.168.1.228:8200`. ElevenLabs widget loads in the mobile browser. BOB responds in under a second. No external exposure needed.

**Away from home** — phone connects through a Cloudflare Tunnel that securely exposes only the dashboard URL to the internet. No ports opened on the router. BOB works identically whether Rob is on the couch or across the country.

Both modes use the same ElevenLabs conversational AI widget — no app to install, no account required on the phone. Just a bookmark.

---

## Prerequisites

- ElevenLabs agent configured with BOB's personality and webhook tools ✓
- Cloudflare account (free tier) — **needs to be created for away-from-home access**
- Ubuntu server running with the dashboard at `:8200` ✓
- Smartphone (Android or iOS) with a browser and microphone ✓

---

## Part A — On the Home Network

This works today once the ElevenLabs agent is deployed. No extra infrastructure needed.

---

**Step 1 — Connect phone to the home WiFi network**

Ensure the phone is on the same WiFi network as the Ubuntu server (`192.168.1.228`).

---

**Step 2 — Open the BOB dashboard in mobile browser**

On the phone, open Chrome (Android) or Safari (iOS) and navigate to:

```
http://192.168.1.228:8200
```

The Debate Arena dashboard loads. The BOB chat panel and ElevenLabs voice widget are embedded here.

---

**Step 3 — Grant microphone permission**

The first time the ElevenLabs widget activates, the browser will ask for microphone access. Tap **Allow**. This is a one-time prompt — the browser remembers it for this site.

> **iOS note:** Safari requires HTTPS for microphone access on external sites, but for local LAN addresses (`192.168.1.x`) it allows HTTP microphone access. If the widget doesn't request mic permission, try Chrome on iOS instead.

---

**Step 4 — Add to home screen for app-like access**

**Android (Chrome):**
1. Tap the three-dot menu in Chrome
2. Tap **Add to Home screen**
3. Name it `BOB`
4. Tap **Add**

**iOS (Safari):**
1. Tap the Share button (box with arrow)
2. Tap **Add to Home Screen**
3. Name it `BOB`
4. Tap **Add**

BOB now appears on the home screen as an icon. One tap opens the dashboard directly — no URL typing.

---

**Step 5 — Test voice on the phone**

With the dashboard open on the phone:
1. Tap the ElevenLabs voice widget button
2. Say something to BOB
3. BOB should respond in his voice through the phone speaker

If it works — Part A is complete. Rob can talk to BOB from anywhere in the house.

Confirm with Rob before proceeding to Part B.

---

## Part B — Away From Home (Cloudflare Tunnel)

When Rob leaves the house, the phone is no longer on the home network. The dashboard at `192.168.1.228:8200` is unreachable. A Cloudflare Tunnel creates a secure public URL that routes directly to the dashboard — without opening any ports on the router.

---

**Step 6 — Create a free Cloudflare account**

On the Windows laptop, open a browser and go to:

```
https://dash.cloudflare.com/sign-up
```

Create a free account with an email and password. No payment required.

---

**Step 7 — SSH into the Ubuntu server**

```powershell
# [WINDOWS]
ssh blueridge@192.168.1.228
```

Confirm connected. Do not proceed until confirmed.

---

**Step 8 — Install cloudflared on the server**

```bash
# [UBUNTU SERVER]
# Add Cloudflare's package repo
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg

echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
  https://pkg.cloudflare.com/cloudflared any main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list

sudo apt update
sudo apt install cloudflared -y
```

Verify install:

```bash
cloudflared --version
```

---

**Step 9 — Authenticate cloudflared with your Cloudflare account**

```bash
# [UBUNTU SERVER]
cloudflared tunnel login
```

This prints a URL. Copy it, paste it into a browser on the Windows laptop, and log in to your Cloudflare account. Click **Authorize**. The server gets a certificate automatically.

---

**Step 10 — Create the tunnel**

```bash
# [UBUNTU SERVER]
cloudflared tunnel create bob-dashboard
```

Output will show:
```
Created tunnel bob-dashboard with id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Copy the tunnel ID. You need it in Step 11.

---

**Step 11 — Create the tunnel config file**

```bash
# [UBUNTU SERVER]
nano ~/.cloudflared/config.yml
```

Paste the following, replacing `YOUR_TUNNEL_ID` with the ID from Step 10:

```yaml
tunnel: YOUR_TUNNEL_ID
credentials-file: /home/blueridge/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  - service: http://localhost:8200
```

Save and exit (`Ctrl+X`, `Y`, `Enter`).

> **Security note:** This exposes only the dashboard at `:8200`. The orchestrator API at `:8100` is NOT exposed — webhook tools call it from within the Docker network. BOB's webhook firewall (from the security plan) adds an additional layer on top of this.

---

**Step 12 — Create a DNS hostname for the tunnel**

You need a domain name for the tunnel URL. Cloudflare provides a free subdomain under `cfargotunnel.com`, but a custom domain looks cleaner. If you don't have a domain, use the free option:

```bash
# [UBUNTU SERVER]
# Option A — Free Cloudflare subdomain (no domain needed)
cloudflared tunnel route dns bob-dashboard bob.YOUR_ACCOUNT_ID.cfargotunnel.com

# Option B — If you own a domain (e.g. attoysgames.com) and it's on Cloudflare DNS
cloudflared tunnel route dns bob-dashboard bob.appalachiantoysgames.com
```

For now use Option A unless you already have a domain on Cloudflare. The URL will look like:
```
https://bob.xxxxxxxx.cfargotunnel.com
```

Write this URL down — it's what goes on the phone.

---

**Step 13 — Run the tunnel as a system service**

```bash
# [UBUNTU SERVER]
# Install as a systemd service so it starts automatically on boot
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

Verify it's running:

```bash
sudo systemctl status cloudflared
```

Should show `active (running)`.

---

**Step 14 — Test the tunnel from the phone**

Take the phone off WiFi (switch to mobile data) and open:

```
https://bob.xxxxxxxx.cfargotunnel.com
```

The BOB dashboard should load over HTTPS from anywhere. The ElevenLabs widget should work exactly as it does on the home network.

> **HTTPS and microphone:** Because this is served over HTTPS, mobile browsers will grant microphone access without any workaround. This is actually better behavior than the local HTTP access in Part A.

Confirm working with Rob before proceeding to Step 15.

---

**Step 15 — Update the phone home screen bookmark**

Now that the tunnel is working, update the phone's home screen icon to use the public tunnel URL instead of the local IP — so one bookmark works both at home and away.

Remove the existing `192.168.1.228:8200` shortcut and add a new one for the tunnel URL following the same steps as Step 4.

---

**Step 16 — Add tunnel health to BOB's monitoring**

Add a tunnel status check to the server monitoring so BOB knows if the tunnel drops:

```python
# orchestrator/network_monitor.py — add to SERVICES dict

"cloudflare_tunnel": {
    "url":     "https://bob.YOUR_SUBDOMAIN.cfargotunnel.com/health",
    "headers": {},
    "method":  "GET",
    "timeout": 10,
    "expect":  [200, 404],   # 404 is fine — means tunnel is alive, path just 404s
    "affects": ["Phone access to BOB from outside home network"],
    "critical": False,
},
```

BOB will alert Rob if the tunnel goes down:
> *"WARNING — Cloudflare tunnel is unreachable. Phone access to BOB from outside the home network is down. Check: `sudo systemctl status cloudflared` on the server."*

---

## Summary — What's Done After These Steps

| Capability | Status |
|---|---|
| Talk to BOB from phone on home WiFi | ✓ |
| BOB accessible at `192.168.1.228:8200` on LAN | ✓ |
| Dashboard bookmarked as app icon on phone home screen | ✓ |
| Microphone permission granted in mobile browser | ✓ |
| Cloudflare Tunnel serving dashboard over HTTPS | ✓ |
| Public URL accessible from anywhere on mobile data | ✓ |
| No router ports opened — all traffic through Cloudflare | ✓ |
| Tunnel auto-starts on server reboot | ✓ |
| Tunnel health monitored — BOB alerts if it drops | ✓ |
| Single bookmark works both at home and away | ✓ |

---

### How it works in practice

**At home on WiFi:**
Rob taps the BOB icon on his phone home screen. Dashboard loads instantly from the local network. Taps the voice widget. Talks to BOB.

**Away from home on mobile data:**
Same icon. Cloudflare routes the request through the tunnel to the server. Dashboard loads over HTTPS. Voice widget works identically.

**BOB's behavior is identical in both cases** — same personality, same webhook tools, same server access. The phone is just another interface.

---

### Two-scenario quick reference

| | Home WiFi | Away from home |
|---|---|---|
| URL | `http://192.168.1.228:8200` | `https://bob.xxx.cfargotunnel.com` |
| Latency | <50ms (LAN) | 100–200ms (internet) |
| HTTPS required | No (LAN exemption) | Yes (auto via Cloudflare) |
| Setup needed | None beyond ElevenLabs deploy | Steps 6–16 above |
| Cost | Free | Free (Cloudflare free tier) |

---

*BOB Phone Access Build Plan v1.0 — 2026-03-18*
*Next build: Push Notifications to Rob's Phone (ntfy)*
