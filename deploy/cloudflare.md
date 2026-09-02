# Cloudflare deployment

- Public hostname: `https://octra.ajpanda.com`
- Tunnel name: `octra-validator-dashboard`
- Tunnel ID: `aa3d7bd9-044a-4200-a584-bdd840a31518`
- Origin: `http://127.0.0.1:8789`
- Connector credential: `/etc/octra-dashboard/cloudflared-token` (not committed)
- Connector image: pinned by digest in `compose.yaml`

The hostname is public. The origin has no public listener and the dashboard/API
expose only allowlisted validator telemetry.
