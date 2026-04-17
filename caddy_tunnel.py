# caddy_tunnel.py
# Usa el Caddy existente como reverse proxy hacia el bot Go
# ============================================================

import subprocess
import sys
import os
import urllib.request
import json
import time
import socket

BOT_PORT  = 8080
CADDY_API = "http://127.0.0.1:2019"

# ============================================================
# CADDY ADMIN API
# ============================================================

def caddy_request(method, path, data=None):
    """Hace una request a la Admin API de Caddy"""
    url = f"{CADDY_API}{path}"
    
    body = json.dumps(data).encode() if data else None
    
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            resp_body = r.read()
            if resp_body:
                return json.loads(resp_body)
            return {"ok": True}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise Exception(f"Caddy API {method} {path} → {e.code}: {body}")
    except urllib.error.URLError as e:
        raise Exception(f"Caddy API no disponible: {e.reason}")


def get_caddy_config():
    """Obtiene config actual de Caddy"""
    return caddy_request("GET", "/config/")


def check_caddy_running():
    """Verifica que Caddy esté corriendo y su API accesible"""
    try:
        cfg = get_caddy_config()
        print("✅ Caddy API accesible")
        return True
    except Exception as e:
        print(f"❌ Caddy no disponible: {e}")
        return False


def check_bot_running(port):
    """Verifica que el bot Go esté escuchando"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        if result == 0:
            print(f"✅ Bot corriendo en puerto {port}")
            return True
        else:
            print(f"⚠️  Nada escuchando en puerto {port}")
            return False
    except Exception as e:
        print(f"❌ Error verificando puerto {port}: {e}")
        return False


# ============================================================
# CONFIGURAR REVERSE PROXY EN CADDY
# ============================================================

def configure_reverse_proxy(bot_port, public_port=2080):
    """
    Configura Caddy como reverse proxy:
    *:PUBLIC_PORT → localhost:BOT_PORT
    """
    
    print(f"\n🔧 Configurando reverse proxy en Caddy...")
    print(f"   Puerto público : {public_port}")
    print(f"   Puerto del bot : {bot_port}")

    # Obtener config actual
    try:
        current = get_caddy_config()
        print("📋 Config actual obtenida")
    except Exception as e:
        print(f"⚠️  No se pudo obtener config actual: {e}")
        current = {}

    # Construir la ruta del reverse proxy
    reverse_proxy_route = {
        "match": [{"path": ["/stream/*"]}],
        "handle": [
            {
                "handler": "reverse_proxy",
                "upstreams": [
                    {"dial": f"127.0.0.1:{bot_port}"}
                ],
                "headers": {
                    "request": {
                        "set": {
                            "X-Forwarded-By": ["caddy-fsb-proxy"],
                            "X-Real-Port":    [str(public_port)]
                        }
                    }
                },
                # Soporte para streaming (no bufferizar)
                "flush_interval": -1,
                # Timeouts para archivos grandes
                "transport": {
                    "protocol": "http",
                    "response_header_timeout": "30s",
                    "dial_timeout": "10s"
                }
            }
        ]
    }

    # Ruta catch-all: todo lo demás también al bot
    catchall_route = {
        "handle": [
            {
                "handler": "reverse_proxy",
                "upstreams": [
                    {"dial": f"127.0.0.1:{bot_port}"}
                ],
                # Crítico para video streaming: no bufferizar
                "flush_interval": -1,
                "transport": {
                    "protocol": "http",
                    "response_header_timeout": "30s",
                    "dial_timeout": "10s"
                }
            }
        ]
    }

    # Config completa del server
    server_config = {
        "listen": [f":{public_port}"],
        "routes": [
            reverse_proxy_route,
            catchall_route
        ],
        # Logging
        "logs": {
            "logger_names": {
                "fsb-proxy": "*"
            }
        }
    }

    # Intentar método 1: PATCH en servers existentes
    try:
        caddy_request(
            "POST",
            "/config/apps/http/servers/fsb_proxy",
            server_config
        )
        print("✅ Servidor proxy configurado via PATCH")
        return True

    except Exception as e:
        print(f"⚠️  PATCH falló: {e}")
        print("🔄 Intentando configuración completa...")

    # Intentar método 2: Config completa
    try:
        full_config = {
            "apps": {
                "http": {
                    "servers": {
                        "fsb_proxy": server_config
                    }
                }
            }
        }

        # Merge con config existente si hay
        if current and "apps" in current:
            if "http" in current["apps"]:
                existing_servers = current["apps"]["http"].get("servers", {})
                existing_servers["fsb_proxy"] = server_config
                full_config["apps"]["http"]["servers"] = existing_servers

        caddy_request("POST", "/load", full_config)
        print("✅ Config completa cargada")
        return True

    except Exception as e:
        print(f"❌ Config completa falló: {e}")
        return False


# ============================================================
# CONFIGURAR PUERTO ALTERNATIVO SI 2080 NO FUNCIONA
# ============================================================

def find_available_port(start=2080, end=9000, exclude=[2019, 8888]):
    """Encuentra un puerto libre para Caddy"""
    for port in range(start, end):
        if port in exclude:
            continue
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(("0.0.0.0", port))
            s.close()

            # Si podemos bind, está libre
            s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s2.bind(("0.0.0.0", port))
            s2.close()
            return port
        except:
            continue
    return None


# ============================================================
# MOSTRAR INFO DEL PROXY
# ============================================================

def show_proxy_info(public_port, bot_port):
    """Muestra la información del proxy configurado"""
    
    # Obtener IP pública
    public_ip = "TU_IP"
    try:
        with urllib.request.urlopen(
            "https://api.ipify.org", timeout=5
        ) as r:
            public_ip = r.read().decode().strip()
    except:
        try:
            with urllib.request.urlopen(
                "https://icanhazip.com", timeout=5
            ) as r:
                public_ip = r.read().decode().strip()
        except:
            pass

    base_url = f"http://{public_ip}:{public_port}"

    print(f"\n{'='*55}")
    print(f"✅ PROXY ACTIVO via Caddy")
    print(f"{'='*55}")
    print(f"🌐 IP Pública    : {public_ip}")
    print(f"📡 Puerto público: {public_port}")
    print(f"🤖 Bot interno   : 127.0.0.1:{bot_port}")
    print(f"{'='*55}")
    print(f"\n📋 Configura tu .env:")
    print(f"   HOST={base_url}")
    print(f"\n📋 Configura el Worker de Cloudflare:")
    print(f"   BOT_SERVER={base_url}")
    print(f"\n🔗 Endpoints disponibles:")
    print(f"   Stream : {base_url}/stream/MSG_ID?hash=HASH")
    print(f"   Health : {base_url}/health")
    print(f"{'='*55}\n")

    return base_url


# ============================================================
# VERIFICAR QUE EL PROXY FUNCIONA
# ============================================================

def verify_proxy(public_port, bot_port):
    """Verifica que el proxy esté funcionando correctamente"""
    print("\n🔍 Verificando proxy...")
    time.sleep(2)

    # Test 1: Caddy responde en el puerto público
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex(("127.0.0.1", public_port))
        s.close()
        if result == 0:
            print(f"✅ Caddy escuchando en :{public_port}")
        else:
            print(f"⚠️  Caddy NO escucha en :{public_port}")
    except Exception as e:
        print(f"❌ Error verificando Caddy: {e}")

    # Test 2: Request de prueba al proxy
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{public_port}/health",
            headers={"User-Agent": "fsb-proxy-check"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
            print(f"✅ Proxy responde: HTTP {status}")
    except urllib.error.HTTPError as e:
        # 404 es ok, significa que llegó al bot
        if e.code in [404, 400, 401]:
            print(f"✅ Proxy funciona (bot respondió {e.code})")
        else:
            print(f"⚠️  Proxy respondió: HTTP {e.code}")
    except Exception as e:
        print(f"⚠️  No se pudo verificar proxy: {e}")


# ============================================================
# MONITOR: Verificar que el bot sigue vivo
# ============================================================

def monitor_bot(bot_port, interval=30):
    """Monitorea que el bot siga corriendo"""
    import threading

    def _monitor():
        while True:
            time.sleep(interval)
            if not check_bot_running(bot_port):
                print(f"\n⚠️  [{time.strftime('%H:%M:%S')}] Bot caído en :{bot_port}")
                print(f"   Reinicia el bot Go para restaurar el servicio")
            else:
                print(f"✅ [{time.strftime('%H:%M:%S')}] Bot OK en :{bot_port}")

    t = threading.Thread(target=_monitor, daemon=True)
    t.start()
    return t


# ============================================================
# REMOVER CONFIGURACIÓN (cleanup)
# ============================================================

def remove_proxy_config():
    """Elimina la configuración del proxy de Caddy"""
    try:
        caddy_request("DELETE", "/config/apps/http/servers/fsb_proxy")
        print("✅ Configuración del proxy eliminada")
    except Exception as e:
        print(f"⚠️  No se pudo eliminar config: {e}")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 55)
    print("🔌 FSB Caddy Proxy Manager")
    print("=" * 55)

    # Argumentos
    bot_port    = int(sys.argv[1]) if len(sys.argv) > 1 else BOT_PORT
    public_port = int(sys.argv[2]) if len(sys.argv) > 2 else 2080

    print(f"\n⚙️  Bot port    : {bot_port}")
    print(f"⚙️  Public port : {public_port}")

    # 1. Verificar Caddy
    if not check_caddy_running():
        print("\n❌ Caddy no está corriendo o su API no es accesible")
        print("   Verifica que Caddy esté activo con: ss -tlnp | grep caddy")
        sys.exit(1)

    # 2. Verificar bot (advertencia, no bloquear)
    check_bot_running(bot_port)

    # 3. Verificar puerto público disponible
    print(f"\n🔍 Verificando puerto {public_port}...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        # Si conecta, alguien ya usa ese puerto
        result = s.connect_ex(("127.0.0.1", public_port))
        s.close()
        if result == 0:
            print(f"ℹ️  Puerto {public_port} ya está en uso (puede ser Caddy mismo)")
        else:
            print(f"✅ Puerto {public_port} disponible")
    except:
        pass

    # 4. Configurar reverse proxy
    success = configure_reverse_proxy(bot_port, public_port)

    if not success:
        print("\n❌ No se pudo configurar el proxy automáticamente")
        print("\n📋 Configuración manual del Caddyfile:")
        print(f"""
:{public_port} {{
    reverse_proxy 127.0.0.1:{bot_port} {{
        flush_interval -1
        transport http {{
            response_header_timeout 30s
        }}
    }}
}}
        """)
        print("Luego ejecuta: caddy reload")
        sys.exit(1)

    # 5. Mostrar info
    base_url = show_proxy_info(public_port, bot_port)

    # 6. Verificar que funciona
    verify_proxy(public_port, bot_port)

    # 7. Monitor en background
    print("🔄 Iniciando monitor del bot (cada 30s)...")
    monitor_bot(bot_port, interval=30)

    print("⌨️  Ctrl+C para detener\n")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo...")
        remove_proxy_config()
        print("✅ Proxy eliminado de Caddy")


if __name__ == "__main__":
    main()
