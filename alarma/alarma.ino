const int LED_PIN = 2; 
const int BUZZER_PIN = 3;

char currentState = 'O';
bool postureBeepDone = false;
unsigned long lastBlinkTime = 0;
bool ledState = LOW;

void setup() {
  Serial.begin(9600);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
}

// Función de Interrupción para Microsueños
void executeMicroSleepAlarm(int blinks) {
  digitalWrite(LED_PIN, LOW);
  tone(BUZZER_PIN, 2000); // Tono grave y fuerte

  // Dividimos los 2 segundos (2000ms) entre los parpadeos
  int blinkDelay = 2000 / (blinks * 2); 

  for(int i = 0; i < blinks; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(blinkDelay);
    digitalWrite(LED_PIN, LOW);
    delay(blinkDelay);
  }
  noTone(BUZZER_PIN);
}

void loop() {
  // 1. Escuchar a Python
  while (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == '\n' || cmd == '\r') continue;

    if (cmd == 'O') {
      currentState = 'O';
      postureBeepDone = false; // Reseteamos el pitido para la próxima vez
      digitalWrite(LED_PIN, LOW);
      noTone(BUZZER_PIN);
    }
    else if (cmd == 'P') {
      currentState = 'P';
    }
    else if (cmd == 'M') {
      executeMicroSleepAlarm(2); // Evento: 2 segs, 2 parpadeos
    }
    else if (cmd == 'F') {
      executeMicroSleepAlarm(4); // Evento: 2 segs, 4 parpadeos
    }
  }

  // 2. Máquina de Estados Continua
  if (currentState == 'P') {
    // A. Un solo pitido fuerte al entrar en mala postura
    if (!postureBeepDone) {
      tone(BUZZER_PIN, 1200, 500); // Pitido de medio segundo
      postureBeepDone = true;
    }

    // B. Parpadeo continuo sin usar delay()
    if (millis() - lastBlinkTime > 250) { 
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState);
      lastBlinkTime = millis();
    }
  }
}