import cv2
import mediapipe as mp
import time
import math
import tkinter as tk
from tkinter import ttk
import serial
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# ---------------------------------------------------------
# 1. CONFIGURACIÓN DE MODELOS E IA
# ---------------------------------------------------------
base_pose = python.BaseOptions(model_asset_path='pose_landmarker_heavy.task')
base_face = python.BaseOptions(model_asset_path='face_landmarker.task')

opt_pose = vision.PoseLandmarkerOptions(base_options=base_pose, running_mode=vision.RunningMode.VIDEO)
opt_face = vision.FaceLandmarkerOptions(base_options=base_face, running_mode=vision.RunningMode.VIDEO)

# ---------------------------------------------------------
# 2. CONFIGURACIÓN DE ARDUINO
# ---------------------------------------------------------
try:
    arduino = serial.Serial('COM10', 9600, timeout=0.1)
    time.sleep(2)
    print("ENLACE EXITOSO: Arduino conectado.")
except:
    arduino = None
    print("MODO SOFTWARE: No se detectó Arduino.")

estado_serial_anterior = "O"

# ---------------------------------------------------------
# 3. VARIABLES DE INICIALIZACIÓN Y ESTADOS
# ---------------------------------------------------------
ultimo_segundo_enviado = -1   # <--- Nueva variable
calibrado = False
ref_postura = 0
suma_postura = 0
f_calib = 0
conteo_mala_postura = 0
TOLERANCIA_ESTRICTA = 0.05
UMBRAL_CUELLO_Z = 0.05
FRAMES_PERSISTENCIA = 10

contador_bostezos = 0
bostezo_activo = False
frames_sin_bostezo = 0
UMBRAL_MAR = 0.5       
UMBRAL_EAR_OC = 0.050  

UMBRAL_MICROSUEÑO = 0.010  
TIEMPO_MICROSUEÑO_SEG = 10    
ojos_cerrados_activo = False
inicio_ojos_cerrados = 0
contador_microsuenos = 0     
LIMITE_MICROSUENOS = 3       

LIMITE_BOSTEZOS = 5
TIEMPO_DESCANSO_SEG = 60
en_descanso = False
inicio_descanso = 0

clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))

# ---------------------------------------------------------
# 4. LAUNCHER: INTERFAZ
# ---------------------------------------------------------
def buscar_camaras():
    camaras_disponibles = []
    for i in range(3):
        cap_temp = cv2.VideoCapture(i, cv2.CAP_DSHOW) 
        if cap_temp.isOpened():
            camaras_disponibles.append(i)
            cap_temp.release()
    return camaras_disponibles

indice_camara_elegida = 0

def iniciar_sensor():
    global indice_camara_elegida
    seleccion = combo_camaras.get()
    if seleccion:
        indice_camara_elegida = int(seleccion.split(" ")[1])
    ventana.destroy() 

ventana = tk.Tk()
ventana.title("Detector De Cansancio")
ventana.geometry("380x200")
try: ventana.eval('tk::PlaceWindow . center') 
except: pass 

tk.Label(ventana, text="Detector de cansancio", font=("Arial", 12, "bold")).pack(pady=10)
tk.Label(ventana, text="Selecciona la cámara de video:", font=("Arial", 10)).pack(pady=5)

lista_camaras = buscar_camaras()
opciones_camaras = [f"Cámara {i}" for i in lista_camaras]

combo_camaras = ttk.Combobox(ventana, values=opciones_camaras, state="readonly", font=("Arial", 11), width=20)
if opciones_camaras:
    combo_camaras.current(0)
else:
    combo_camaras.set("No se detectaron cámaras")
combo_camaras.pack(pady=5)

tk.Button(ventana, text="INICIAR IA", font=("Arial", 11, "bold"), bg="#4CAF50", fg="white", 
          command=iniciar_sensor, width=15).pack(pady=15)

ventana.mainloop() 

# ---------------------------------------------------------
# 5. BUCLE PRINCIPAL DE PROCESAMIENTO
# ---------------------------------------------------------
with vision.PoseLandmarker.create_from_options(opt_pose) as pose_det, \
     vision.FaceLandmarker.create_from_options(opt_face) as face_det:
    
    cap = cv2.VideoCapture(indice_camara_elegida, cv2.CAP_DSHOW)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l_mej = clahe.apply(l)
        frame_proc = cv2.cvtColor(cv2.merge((l_mej, a, b)), cv2.COLOR_LAB2BGR)

       # =========================================================
        # MODO A: PANTALLA DE DESCANSO ACTIVO
        # =========================================================
        if en_descanso:
            tiempo_actual = time.time()
            tiempo_restante = int(TIEMPO_DESCANSO_SEG - (tiempo_actual - inicio_descanso))

            if tiempo_restante <= 0:
                en_descanso = False
                contador_bostezos = 0
                contador_microsuenos = 0  
                bostezo_activo = False 
                ojos_cerrados_activo = False
            else:
                cv2.rectangle(frame_proc, (0, 0), (w, h), (0, 0, 0), -1)
                cv2.putText(frame_proc, "ALERTA DE FATIGA EXTREMA", (w//2 - 200, h//2 - 50), 1, 2, (0, 0, 255), 3)
                cv2.putText(frame_proc, f"Descanso activo: {tiempo_restante}s", (w//2 - 180, h//2 + 10), 1, 1.8, (0, 255, 255), 2)
                cv2.putText(frame_proc, "Levantate, estira y toma agua.", (w//2 - 200, h//2 + 70), 1, 1.2, (255, 255, 255), 1)

                # ---> NUEVA LOGICA: ENVIAR CRONÓMETRO A LA LCD <---
                if arduino is not None and tiempo_restante != ultimo_segundo_enviado:
                    arduino.write(f"D,{tiempo_restante}\n".encode())
                    ultimo_segundo_enviado = tiempo_restante
                    estado_serial_anterior = "D"

        # =========================================================
        # MODO B: PROCESAMIENTO IA NORMAL
        # =========================================================
        else:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_proc)
            ts = int(time.time() * 1000)
            
            res_pose = pose_det.detect_for_video(mp_image, ts)
            res_face = face_det.detect_for_video(mp_image, ts)

            bostezo_detectado = False
            ear_valor = 0.1 
            mano_cerca_rostro = False # <--- 1. NUEVA BANDERA DE SEGURIDAD

            # --- 1. ROSTRO: BOSTEZOS Y MICROSUEÑOS ---
            if res_face.face_landmarks:
                f_lm = res_face.face_landmarks[0]
                v_m = math.hypot(f_lm[13].x - f_lm[14].x, f_lm[13].y - f_lm[14].y)
                h_m = math.hypot(f_lm[78].x - f_lm[308].x, f_lm[78].y - f_lm[308].y)
                mar = v_m / h_m
                ear_valor = f_lm[145].y - f_lm[159].y

                if mar > UMBRAL_MAR:
                    bostezo_detectado = True
                    cv2.putText(frame_proc, "BOSTEZO ABIERTO", (w-300, 50), 1, 1.3, (0, 255, 0), 2)

                if ear_valor < UMBRAL_MICROSUEÑO:
                    if not ojos_cerrados_activo:
                        ojos_cerrados_activo = True
                        inicio_ojos_cerrados = time.time() 
                    else:
                        tiempo_cerrado = time.time() - inicio_ojos_cerrados
                        
                        if tiempo_cerrado >= 2:
                            cv2.putText(frame_proc, f"DURMIENDO: {int(tiempo_cerrado)}s", (20, 90), 1, 1.5, (0, 0, 255), 2)
                        
                        if tiempo_cerrado >= TIEMPO_MICROSUEÑO_SEG:
                            contador_microsuenos += 1
                            ojos_cerrados_activo = False 
                            
                            if contador_microsuenos >= LIMITE_MICROSUENOS:
                                if arduino is not None: arduino.write(b"F\n") 
                                en_descanso = True
                                inicio_descanso = time.time()
                            else:
                                if arduino is not None: arduino.write(b"M\n") 
                else:
                    ojos_cerrados_activo = False

            # --- 2. OCLUSIÓN: BOSTEZO CUBIERTO (Y DETECCIÓN DE MANO) ---
            if res_pose.pose_landmarks:
                p_lm = res_pose.pose_landmarks[0]
                d_izq = math.hypot(p_lm[19].x - p_lm[0].x, p_lm[19].y - p_lm[0].y)
                d_der = math.hypot(p_lm[20].x - p_lm[0].x, p_lm[20].y - p_lm[0].y)
                UMBRAL_MANO_NARIZ = 0.15
                cara_oculta = not res_face.face_landmarks

                cv2.putText(frame_proc, f"Dist Mano: I={d_izq:.2f} D={d_der:.2f}", (10, 160), 1, 1.5, (0, 255, 255), 2)
                cv2.putText(frame_proc, f"EAR Ojo: {ear_valor:.3f}", (10, 190), 1, 1.5, (0, 255, 255), 2)

                if d_izq < UMBRAL_MANO_NARIZ or d_der < UMBRAL_MANO_NARIZ:
                    mano_cerca_rostro = True # <--- Activamos la bandera si la mano sube
                    if not bostezo_detectado and (cara_oculta or ear_valor < UMBRAL_EAR_OC):
                        bostezo_detectado = True
                        cv2.putText(frame_proc, "BOSTEZO CUBIERTO", (w-350, 50), 1, 1.3, (255, 0, 255), 2)

            # --- 3. POSTURA (AHORA EVALUADA AL FINAL PARA USAR EL FILTRO) ---
            if res_pose.pose_landmarks:
                p_lm = res_pose.pose_landmarks[0]
                y_nariz = p_lm[0].y
                y_hombros = (p_lm[11].y + p_lm[12].y) / 2
                x_oreja = (p_lm[7].x + p_lm[8].x) / 2
                x_hombros = (p_lm[11].x + p_lm[12].x) / 2
                
                dist_v_actual = y_hombros - y_nariz
                offset_cuello = abs(x_oreja - x_hombros)

                for pt in p_lm:
                    cv2.circle(frame_proc, (int(pt.x*w), int(pt.y*h)), 2, (0, 255, 0), -1)

                if not calibrado:
                    f_calib += 1
                    suma_postura += dist_v_actual
                    cv2.putText(frame_proc, f"CALIBRANDO RIGIDEZ: {f_calib}/60", (20, 50), 1, 1.5, (0, 255, 255), 2)
                    if f_calib >= 60:
                        ref_postura = suma_postura / 60
                        calibrado = True
                else:
                    caida = dist_v_actual < (ref_postura * (1 - TOLERANCIA_ESTRICTA))
                    adelanto = offset_cuello > UMBRAL_CUELLO_Z

                    # <--- 2. LÓGICA DE EXCLUSIÓN MUTUA --->
                    if mano_cerca_rostro or bostezo_detectado:
                        # Si te tapas la boca o bostezas, pausamos el conteo
                        cv2.putText(frame_proc, "POSTURA EN PAUSA (MOVIMIENTO)", (20, 45), 1, 1.2, (255, 165, 0), 2)
                    elif caida or adelanto:
                        conteo_mala_postura += 1
                    else:
                        if conteo_mala_postura > 0: conteo_mala_postura -= 2 
                        if conteo_mala_postura < 0: conteo_mala_postura = 0

                    # 3. Interfaz de Postura
                    if conteo_mala_postura >= FRAMES_PERSISTENCIA:
                        cv2.rectangle(frame_proc, (0,0), (w, 75), (0,0,255), -1)
                        cv2.putText(frame_proc, "CRITICO: MALA POSTURA", (20, 50), 1, 1.8, (255, 255, 255), 3)
                    elif not (mano_cerca_rostro or bostezo_detectado):
                        cv2.putText(frame_proc, "ESTADO: POSTURA OPTIMA", (20, 45), 1, 1.2, (0, 255, 0), 2)

            # --- 4. GESTIÓN DE ESTADOS CONTINUOS ---
            if bostezo_detectado:
                frames_sin_bostezo = 0 
                if not bostezo_activo:
                    contador_bostezos += 1
                    bostezo_activo = True
                    
                    if contador_bostezos >= LIMITE_BOSTEZOS:
                        if arduino is not None: arduino.write(b"F\n") 
                        en_descanso = True
                        inicio_descanso = time.time()
            else:
                frames_sin_bostezo += 1
                if frames_sin_bostezo > 15:
                    bostezo_activo = False

            # --- 5. TRANSMISIÓN DE POSTURA (ESTADOS) ---
            if arduino is not None:
                estado_actual = "P" if conteo_mala_postura >= FRAMES_PERSISTENCIA else "O"
                if estado_actual != estado_serial_anterior:
                    arduino.write(f"{estado_actual}\n".encode())
                    estado_serial_anterior = estado_actual

            cv2.putText(frame_proc, f"BOSTEZOS: {contador_bostezos}/{LIMITE_BOSTEZOS}", (20, h-70), 1, 1.5, (255, 255, 255), 2)
            cv2.putText(frame_proc, f"ETAPAS SUENO: {contador_microsuenos}/{LIMITE_MICROSUENOS}", (20, h-30), 1, 1.5, (0, 165, 255), 2)

        cv2.imshow('Detector De Cansancio', frame_proc)
        if cv2.waitKey(1) & 0xFF == 27: break

cap.release()
if arduino is not None:
    arduino.close()
cv2.destroyAllWindows()