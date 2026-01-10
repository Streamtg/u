import os
import time
import random
import sys
import subprocess

# --- CONFIGURACIÓN DE RUTAS LOCALES ---
# Intentamos localizar el binario de Chrome que ya esté en el servidor
CHROME_PATH = subprocess.getoutput("which google-chrome || which chromium-browser")
USER_HOME = os.path.expanduser("~")
PROFILE_DIR = os.path.join(USER_HOME, "chrome_user_data")

if not os.path.exists(PROFILE_DIR):
    os.makedirs(PROFILE_DIR)

# --- PARÁMETROS ---
URL_VIDEO = "https://dai.ly/x8vyyeq"
TIEMPO_TOTAL = (11 * 3600) + (58 * 60) # 11h 58m
INICIO_GLOBAL = time.time()

print(f"--- [SISTEMA] Iniciando Proceso en CentOS 7 (No-Root) ---")
print(f"--- [INFO] Usando binario: {CHROME_PATH}")

import undetected_chromedriver as uc

def iniciar_navegador():
    options = uc.ChromeOptions()
    
    # MODO HEADLESS NUEVO: Es indetectable y renderiza TODO como una VM real
    options.add_argument('--headless=new') 
    
    options.add_argument(f'--user-data-dir={PROFILE_DIR}')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument("--mute-audio")
    
    # User Agent de alta fidelidad
    options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = None
    try:
        driver = uc.Chrome(options=options, browser_executable_path=CHROME_PATH)
        driver.set_page_load_timeout(60)
        
        print(f"[{time.strftime('%H:%M:%S')}] Navegador activo. Cargando página completa...")
        try:
            driver.get(URL_VIDEO)
        except:
            pass

        # Pausa de 25s para carga total de recursos (Ads/Video)
        time.sleep(25)
        
        ciclo_start = time.time()
        # Cada 25 min reiniciamos para evitar que el proceso de usuario se llene de caché
        while time.time() - ciclo_start < (25 * 60):
            wait_time = random.uniform(15, 40)
            
            # Log de estado
            elapsed = time.time() - INICIO_GLOBAL
            print(f"      Status: OK | Refresh en: {int(wait_time)}s | Total: {int(elapsed//60)}min", end='\r')
            time.sleep(wait_time)
            
            try:
                # Refresh vía JS para máxima estabilidad
                driver.execute_script("location.reload(true);")
            except:
                break
            
            if (time.time() - INICIO_GLOBAL) >= TIEMPO_TOTAL:
                break

    except Exception as e:
        print(f"\n[!] Error en el ciclo: {str(e)[:50]}")
    finally:
        if driver:
            try: driver.quit()
            except: pass
        # Limpieza de procesos de usuario
        os.system("pkill -u $(whoami) chrome")

# --- BUCLE MAESTRO ---
try:
    while (time.time() - INICIO_GLOBAL) < TIEMPO_TOTAL:
        iniciar_navegador()
        time.sleep(5)
except KeyboardInterrupt:
    print("\n[STOP] Proceso detenido.")
