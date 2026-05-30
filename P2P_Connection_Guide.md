# PayrollPro: Peer-to-Peer (P2P) Connection Guide

This guide explains how to connect your computer with your friend's computer over Tailscale (from 10km away) using the new decentralized **P2P Unicast Auto-Negotiation and Failover Sync** system.

---

## 🚀 Step-by-Step Connection Instructions

### 1. Exchange Tailscale IP Addresses
* **Your Tailscale IP:** `100.99.71.76`
* **Your Friend's Tailscale IP:** Ask your friend to open Tailscale and send you their IP address (it will also start with `100.`).

---

### 2. Configure Your Friend's Computer
On your friend's PC, open the app and follow these steps:
1. Navigate to **Settings** in the sidebar.
2. Click on the **Peer-to-Peer Unicast Connection** tab.
3. In the **Peer IP (P2P)** field, enter **your** IP:
   `100.99.71.76`
4. Set the **Port** field to `5050`.
5. Click **💾 Connect & Save**.
6. **Restart the application** to apply the configuration.

---

### 3. Configure Your Computer
On your PC, open the app and follow these steps:
1. Navigate to **Settings** in the sidebar.
2. Click on the **Peer-to-Peer Unicast Connection** tab.
3. In the **Peer IP (P2P)** field, enter **your friend's** Tailscale IP address.
4. Set the **Port** field to `5050`.
5. Click **💾 Connect & Save**.
6. **Restart the application** to apply the configuration.

---

## 🔄 How the P2P Sync Operates

The synchronization and role negotiation are entirely automated and decentralized:

1. **First PC online becomes the Host:**
   * Whichever of you launches the program first will ping the other's IP. 
   * Since the other computer's app is closed, it will find it offline and automatically start as the **Host** (`🟢 Host: Active` will be displayed in the bottom-left corner).
   * It runs the Flask database server (`sync_server.py`) using its local database.

2. **Second PC online becomes the Client:**
   * When the second person opens their app, it pings the Host's IP, finds it active, and automatically connects as the **Client** (`🔵 Client: Synced`).
   * It immediately downloads the latest database backup from the Host, and starts working on the shared data in real-time.

3. **Background Syncing (Zero Data Loss):**
   * While running as a Client, the app polls the Host every 2 seconds.
   * On every change, the Client **automatically downloads a backup copy of the master database** and replaces its local file in the background.

4. **Seamless Failover:**
   * If the Host exits or turns off their computer, the Client detects it within 6 seconds.
   * The Client gracefully **transitions to the Host role**, starts the background Flask server, and continues hosting using the fully synchronized database.
   * When the other person opens the app later, they automatically connect as a Client to the new Host, pull the updated database, and resume work seamlessly!
