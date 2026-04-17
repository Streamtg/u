# fix_caddy.py
# Actualiza la config existente de Caddy agregando
# soporte para streaming (flush_interval, headers, timeouts)
# ============================================================

import urllib.request
import urllib.error
import json
import socket
import time

CADDY_API   = "http://127.0.0.1:2019"
BOT_PORT    = 8080
PUBLIC_PORT = 2080

# ============================================================
# HELPER
# ============================================================

def caddy_request(method, path, data=None):
    url  = f"{CADDY_API}{path}"
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = r.read()
            return json.loads(resp) if resp else {"ok": True}
    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP {e.code}: {e.read().decode()}")
    except urllib.error.URLError as e:
        raise Exception(f"URL Error: {e.reason}")

# ============================================================
# NUEVA CONFIG - srv0 actualizado
# ============================================================

NEW_CONFIG = {
    "listen": [f":{PUBLIC_PORT}"],
    "routes": [
        {
            "handle": [
                {
                    "handler": "reverse_proxy",
                    "upstreams": [
                        {"dial": f"localhost:{BOT_PORT}"}
                    ],

                    # ── Crítico para video streaming ──
                    # -1 = flush inmediato, sin bufferizar
                    "flush_interval": -1,

                    # ── Headers hacia el bot ──
                    "headers": {
                        "request": {
                            "set": {
                                "X-Forwarded-By":   ["caddy-fsb"],
                                "X-Real-Port":      [str(PUBLIC_PORT)],
                                # Preservar IP real del cliente
                                "X-Forwarded-For":  ["{http.request.header.X-Forwarded-For}"],
                                "X-Real-IP":        ["{http.request.remote.host}"]
                            }
                        },
                        "response": {
                            "set": {
                                # Habilitar seeking en players
                                "Accept-Ranges":                ["bytes"],
                                "Access-Control-Allow-Origin":  ["*"],
                                "Access-Control-Allow-Headers": ["Range, Content-Type"],
                                "Access-Control-Expose-Headers":["Content-Range, Content-Length, Accept-Ranges"]
                            }
                        }
                    },

                    # ── Timeouts para archivos grandes ──
                    "transport": {
                        "protocol": "http",
                        "dial_timeout":            "10s",
                        "response_header_timeout": "30s",
                        "read_buffer_size":        16384
                    }
                }
            ]
        }
    ],

    # ── Logs ──
    "logs": {
        "default_logger_name": "fsb"
    }
}

# ============================================================
# APLICAR
# ============================================================

def apply():
    print("="*50)
    print("🔧 Actualizando config de Caddy para FSB")
    print("="*50)

    # 1. Verificar Caddy
    try:
        current = caddy_request("GET", "/config/")
        print("✅ Caddy API accesible")
        print(f"📋 Config actual:\n{json.dumps(current, indent=2)}\n")
    except Exception as e:
        print(f"❌ Caddy no accesible: {e}")
        return False

    # 2. Aplicar nueva config en srv0
    print("⚙️  Aplicando nueva config en srv0...")
    try:
        caddy_request(
            "PATCH",
            "/config/apps/http/servers/srv0",
            NEW_CONFIG
        )
        print("✅ Config aplicada via PATCH")
        success = True
    except Exception as e:
        print(f"⚠️  PATCH falló: {e}")
        print("🔄 Intentando con POST /load completo...")
        try:
            caddy_request("POST", "/load", {
                "apps": {
                    "http": {
                        "servers": {
                            "srv0": NEW_CONFIG
                        }
                    }
                }
            })
            print("✅ Config aplicada via POST /load")
            success = True
        except Exception as e2:
            print(f"❌ POST /load también falló: {e2}")
            success = False

    if not success:
        return False

    # 3. Verificar config resultante
    time.sleep(1)
    try:
        result = caddy_request("GET", "/config/")
        print(f"\n📋 Config final:\n{json.dumps(result, indent=2)}")
    except Exception as e:
        print(f"⚠️  No se pudo leer config final: {e}")

    return True


def get_public_ip():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
            return r.read().decode().strip()
    except:
        try:
            with urllib.request.urlopen("https://icanhazip.com", timeout=5) as r:
                return r.read().decode().strip()
        except:
            return "TU_IP"


def verify():
    print("\n🔍 Verificando proxy...")
    time.sleep(2)

    ip = get_public_ip()

    # Test local
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        r = s.connect_ex(("127.0.0.1", PUBLIC_PORT))
        s.close()
        status = "✅ UP" if r == 0 else "❌ DOWN"
        print(f"  Caddy :{PUBLIC_PORT} → {status}")
    except Exception as e:
        print(f"  Error: {e}")

    # Test HTTP
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PUBLIC_PORT}/health",
            headers={"User-Agent": "fsb-check"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            print(f"  HTTP test → ✅ {r.status}")
    except urllib.error.HTTPError as e:
        # 404/400 significa que llegó al bot
        if e.code in [404, 400, 401]:
            print(f"  HTTP test → ✅ Bot respondió {e.code}")
        else:
            print(f"  HTTP test → ⚠️  {e.code}")
    except Exception as e:
        print(f"  HTTP test → ⚠️  {e}")

    # Mostrar info final
    print(f"""
{'='*50}
✅ PROXY LISTO

🌐 IP pública    : {ip}
📡 Puerto público: {PUBLIC_PORT}
🤖 Bot interno   : localhost:{BOT_PORT}

📋 Configura en .env del bot:
   HOST=http://{ip}:{PUBLIC_PORT}

📋 Configura en el Worker CF:
   BOT_SERVER=http://{ip}:{PUBLIC_PORT}

🔗 URL de stream:
   http://{ip}:{PUBLIC_PORT}/stream/MSG_ID?hash=HASH
{'='*50}
    """)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    ok = apply()
    if ok:
        verify()
    else:
        print(f"""
❌ No se pudo actualizar via API.

📋 Opción manual - edita el Caddyfile y agrega:
   :{PUBLIC_PORT} {{
       reverse_proxy localhost:{BOT_PORT} {{
           flush_interval -1
           header_up X-Forwarded-By caddy-fsb
           header_down Accept-Ranges bytes
           header_down Access-Control-Allow-Origin *
       }}
   }}

Luego: caddy reload --config /ruta/Caddyfile
        """)
