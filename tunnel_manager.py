# tunnel_manager.py
# Túneles que usan solo conexiones SALIENTES (no necesitan puertos abiertos)
# ============================================================

import subprocess
import urllib.request
import urllib.error
import os
import stat
import time
import threading
import sys
import json
import socket

TUNNEL_DIR = os.path.expanduser("~/tunnels")
BOT_PORT   = 2080  # Caddy proxy

os.makedirs(TUNNEL_DIR, exist_ok=True)

# ============================================================
# COLORES
# ============================================================

class C:
    OK   = "\033[92m"
    WARN = "\033[93m"
    ERR  = "\033[91m"
    INFO = "\033[94m"
    BOLD = "\033[1m"
    END  = "\033[0m"

def ok(s):   print(f"{C.OK}✅ {s}{C.END}")
def warn(s): print(f"{C.WARN}⚠️  {s}{C.END}")
def err(s):  print(f"{C.ERR}❌ {s}{C.END}")
def info(s): print(f"{C.INFO}ℹ️  {s}{C.END}")
def bold(s): print(f"{C.BOLD}{s}{C.END}")

# ============================================================
# VERIFICAR CONECTIVIDAD SALIENTE
# ============================================================

def check_outbound():
    bold("\n🔍 Verificando conectividad saliente...")
    
    tests = [
        ("api.ipify.org",         443, "HTTPS"),
        ("bore.pub",              7835,"Bore"),
        ("serveo.net",            22,  "Serveo SSH"),
        ("localhost.run",         22,  "localhost.run SSH"),
        ("pinggy.io",             22,  "Pinggy SSH"),
        ("tunnel.us.ngrok.com",   443, "ngrok HTTPS"),
        ("connect.remotemoe.com", 22,  "remotemoe SSH"),
    ]
    
    available = []
    for host, port, name in tests:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(4)
            r = s.connect_ex((host, port))
            s.close()
            if r == 0:
                ok(f"{name:<20} → {host}:{port}")
                available.append(name)
            else:
                warn(f"{name:<20} → bloqueado ({host}:{port})")
        except Exception as e:
            warn(f"{name:<20} → error: {e}")
    
    return available

# ============================================================
# 1. BORE (TCP puro, sin SSH, sin cuenta)
# ============================================================

def download_bore():
    path = os.path.join(TUNNEL_DIR, "bore")
    if os.path.exists(path):
        ok("bore ya descargado")
        return path
    
    info("Descargando bore...")
    url = ("https://github.com/ekzhang/bore/releases/download/"
           "v0.5.0/bore-v0.5.0-x86_64-unknown-linux-musl")
    try:
        urllib.request.urlretrieve(url, path)
        os.chmod(path, stat.S_IRWXU)
        ok("bore descargado")
        return path
    except Exception as e:
        err(f"No se pudo descargar bore: {e}")
        return None


def run_bore(port):
    binary = download_bore()
    if not binary:
        return None, None
    
    info(f"Iniciando bore → puerto {port}")
    
    proc = subprocess.Popen(
        [binary, "local", str(port), "--to", "bore.pub"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    
    url = None
    deadline = time.time() + 15
    
    for line in proc.stdout:
        line = line.strip()
        print(f"  [bore] {line}")
        if "bore.pub:" in line:
            for part in line.split():
                if "bore.pub:" in part:
                    remote_port = part.split("bore.pub:")[-1].strip()
                    url = f"http://bore.pub:{remote_port}"
                    break
        if url or time.time() > deadline:
            break
    
    return proc, url

# ============================================================
# 2. SERVEO (SSH reverse tunnel, sin cuenta)
# ============================================================

def run_serveo(port):
    info(f"Iniciando túnel Serveo → puerto {port}")
    
    # Generar clave SSH si no existe
    key_path = os.path.expanduser("~/.ssh/id_rsa_tunnel")
    if not os.path.exists(key_path):
        try:
            subprocess.run(
                ["ssh-keygen", "-t", "rsa", "-b", "2048",
                 "-f", key_path, "-N", "", "-q"],
                check=True, capture_output=True
            )
            ok("Clave SSH generada")
        except Exception as e:
            warn(f"No se pudo generar clave SSH: {e}")
            key_path = None
    
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=10",
        "-R", f"80:localhost:{port}",
        "serveo.net",
    ]
    
    if key_path and os.path.exists(key_path):
        cmd = cmd[:1] + ["-i", key_path] + cmd[1:]
    
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    
    url = None
    deadline = time.time() + 20
    
    for line in proc.stdout:
        line = line.strip()
        print(f"  [serveo] {line}")
        if "https://" in line and "serveo.net" in line:
            for part in line.split():
                if part.startswith("https://") and "serveo.net" in part:
                    url = part
                    break
        if url or time.time() > deadline:
            break
    
    return proc, url

# ============================================================
# 3. LOCALHOST.RUN (SSH, sin cuenta)
# ============================================================

def run_localhost_run(port):
    info(f"Iniciando túnel localhost.run → puerto {port}")
    
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ConnectTimeout=10",
        "-R", f"80:localhost:{port}",
        "nokey@localhost.run",
    ]
    
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    
    url = None
    deadline = time.time() + 25
    
    for line in proc.stdout:
        line = line.strip()
        print(f"  [lhr] {line}")
        if ".lhr.life" in line or "localhost.run" in line:
            for part in line.split():
                if part.startswith("https://"):
                    url = part.strip(",")
                    break
        if url or time.time() > deadline:
            break
    
    return proc, url

# ============================================================
# 4. PINGGY (SSH, sin cuenta, gratis)
# ============================================================

def run_pinggy(port):
    info(f"Iniciando túnel Pinggy → puerto {port}")
    
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ConnectTimeout=10",
        "-p", "443",
        "-R", f"0:localhost:{port}",
        "a.pinggy.io",
    ]
    
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    
    url = None
    deadline = time.time() + 20
    
    for line in proc.stdout:
        line = line.strip()
        print(f"  [pinggy] {line}")
        if "pinggy.link" in line or "pinggy.io" in line:
            for part in line.split():
                if part.startswith("https://"):
                    url = part.strip(",")
                    break
        if url or time.time() > deadline:
            break
    
    return proc, url

# ============================================================
# 5. REMOTEMOE (SSH, sin cuenta)
# ============================================================

def run_remotemoe(port):
    info(f"Iniciando túnel remotemoe → puerto {port}")
    
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ConnectTimeout=10",
        "-R", f"80:localhost:{port}",
        "connect.remotemoe.com",
    ]
    
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    
    url = None
    deadline = time.time() + 20
    
    for line in proc.stdout:
        line = line.strip()
        print(f"  [remotemoe] {line}")
        if "remotemoe.com" in line and "https" in line:
            for part in line.split():
                if part.startswith("https://"):
                    url = part.strip(",")
                    break
        if url or time.time() > deadline:
            break
    
    return proc, url

# ============================================================
# INTENTAR TODOS EN ORDEN
# ============================================================

TUNNELS = [
    ("Bore",           run_bore),
    ("Serveo",         run_serveo),
    ("localhost.run",  run_localhost_run),
    ("Pinggy",         run_pinggy),
    ("remotemoe",      run_remotemoe),
]


def try_all_tunnels(port):
    for name, fn in TUNNELS:
        bold(f"\n{'='*50}")
        bold(f"Probando: {name}")
        bold(f"{'='*50}")
        
        try:
            proc, url = fn(port)
            
            if url:
                return name, proc, url
            else:
                warn(f"{name} no devolvió URL")
                if proc:
                    proc.terminate()
                    
        except FileNotFoundError as e:
            warn(f"{name}: comando no disponible ({e})")
        except Exception as e:
            err(f"{name}: {e}")
        
        time.sleep(2)
    
    return None, None, None

# ============================================================
# MONITOR: reiniciar si el túnel muere
# ============================================================

def monitor(proc, name, fn, port, url_holder):
    while True:
        time.sleep(15)
        if proc.poll() is not None:
            warn(f"\n[{time.strftime('%H:%M:%S')}] Túnel {name} caído, reiniciando...")
            try:
                new_proc, new_url = fn(port)
                if new_url:
                    url_holder[0] = new_url
                    print_success(name, new_url, port)
                    proc = new_proc
            except Exception as e:
                err(f"Error reiniciando {name}: {e}")

# ============================================================
# MOSTRAR RESULTADO FINAL
# ============================================================

def print_success(name, url, port):
    print(f"""
{'='*55}
✅  TÚNEL ACTIVO: {name}
{'='*55}
🌐  URL PÚBLICA : {url}
🤖  Bot local   : http://127.0.0.1:{port}
{'='*55}

📋  Configura el bot (fsb.env):
    HOST=http://127.0.0.1:{port}
    PUBLIC_HOST={url}

📋  Configura el Worker de Cloudflare:
    BOT_PUBLIC_URL={url}

🔗  Player de ejemplo:
    {url}/stream/MSG_ID?hash=HASH
{'='*55}
""")

# ============================================================
# VERIFICAR QUE EL BOT CORRE
# ============================================================

def check_bot(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    r = s.connect_ex(("127.0.0.1", port))
    s.close()
    if r == 0:
        ok(f"Bot/Caddy corriendo en :{port}")
        return True
    else:
        warn(f"Nada escuchando en :{port}")
        warn("Asegúrate de que Caddy/bot estén corriendo primero")
        return False

# ============================================================
# MAIN
# ============================================================

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else BOT_PORT
    
    bold("=" * 55)
    bold("⚡ FSB Tunnel Manager")
    bold("=" * 55)
    
    # 1. Verificar bot
    check_bot(port)
    
    # 2. Ver qué servicios son alcanzables
    available = check_outbound()
    
    if not available:
        err("Ningún servicio de túnel es alcanzable")
        err("El entorno bloquea conexiones salientes también")
        sys.exit(1)
    
    ok(f"\nServicios disponibles: {', '.join(available)}")
    
    # 3. Intentar túneles en orden
    bold("\n🚇 Iniciando túnel...")
    name, proc, url = try_all_tunnels(port)
    
    if not url:
        err("\nNingún túnel funcionó")
        print("""
Opciones manuales:
  1. Pide al administrador de SciServer que abra un puerto
  2. Usa una VPS como intermediario
  3. Configura el worker CF en modo offline (solo HTML)
        """)
        sys.exit(1)
    
    # 4. Resultado
    print_success(name, url, port)
    
    # 5. Monitor en background
    url_holder = [url]
    fn = dict(TUNNELS)[name]
    t  = threading.Thread(
        target=monitor,
        args=(proc, name, fn, port, url_holder),
        daemon=True,
    )
    t.start()
    
    info("Ctrl+C para detener\n")
    
    try:
        proc.wait()
    except KeyboardInterrupt:
        bold("\n🛑 Deteniendo...")
        proc.terminate()
        ok("Túnel cerrado")


if __name__ == "__main__":
    main()
