import time
import cv2
import numpy as np
import os
from PIL import Image
from pinkylib import LED
from pinky_lcd import LCD

print("🤖 핑키 얼굴(LED/LCD) 전용 시스템 가동 완료!")

leds = LED()
lcd = LCD()

COLORS = {
    'RED': (255, 0, 0), 'GREEN': (0, 255, 0), 'BLUE': (0, 0, 255),
    'ORANGE': (255, 127, 0), 'YELLOW': (255, 255, 0), 
    'INDIGO': (75, 0, 130), 'VIOLET': (148, 0, 211), 'BLACK': (0, 0, 0), 'WHITE': (255, 255, 255)
}

current_lcd_text = None
last_led_state = None
rainbow_offset = 0

# 💡 확실한 경로로 수정
STATE_FILE = os.path.expanduser('~/pinky_pro/pinky_state.txt')

def update_lcd(text, bg_color):
    global current_lcd_text
    if current_lcd_text != text:
        img_cv = np.zeros((240, 320, 3), dtype=np.uint8)
        img_cv[:] = [bg_color[2], bg_color[1], bg_color[0]] 
        font = cv2.FONT_HERSHEY_DUPLEX
        text_size = cv2.getTextSize(text, font, 1.2, 2)[0]
        text_x = (320 - text_size[0]) // 2
        text_y = (240 + text_size[1]) // 2
        cv2.putText(img_cv, text, (text_x+2, text_y+2), font, 1.2, (50, 50, 50), 2, cv2.LINE_AA)
        cv2.putText(img_cv, text, (text_x, text_y), font, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
        img_pil = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
        lcd.img_show(img_pil)
        current_lcd_text = text

def show_rainbow():
    global rainbow_offset
    rainbow_colors = [COLORS['RED'], COLORS['ORANGE'], COLORS['YELLOW'], COLORS['GREEN'], 
                      COLORS['BLUE'], COLORS['INDIGO'], COLORS['VIOLET'], COLORS['WHITE']]
    for i in range(8):
        idx = (i + rainbow_offset) % 8
        leds.set_pixel(i, rainbow_colors[idx])
    leds.show()
    rainbow_offset += 1

try:
    update_lcd("SYSTEM BOOT", COLORS['BLACK'])
    while True:
        try:
            with open(STATE_FILE, 'r') as f:
                state = f.read().strip()
            # 💡 파일을 쓰는 찰나에 비어있으면 에러 방지
            if not state: 
                state = "WAITING"
        except:
            state = "WAITING"

        # 💡 상태가 바뀔 때마다 터미널에 출력해서 증거를 남김!
        if state != last_led_state and state != "FOLLOWING":
            print(f"💌 뇌로부터 받은 상태: {state}")
        elif state == "FOLLOWING" and last_led_state != "FOLLOWING":
            print(f"🌈 무지개 파워 ON!! 상태: {state}")

        if state == "EMERGENCY":
            update_lcd("EMERGENCY!", COLORS['RED'])
            if last_led_state != "EMERGENCY":
                leds.fill(COLORS['RED']); leds.show(); last_led_state = "EMERGENCY"
        
        elif state == "FOLLOWING":
            update_lcd("FOLLOWING...", COLORS['BLACK'])
            show_rainbow() 
            last_led_state = "FOLLOWING"
            
        elif state == "ARRIVED":
            update_lcd("ARRIVED!", COLORS['GREEN'])
            if last_led_state != "ARRIVED":
                leds.fill(COLORS['GREEN']); leds.show(); last_led_state = "ARRIVED"
                
        else: 
            update_lcd("WAITING TARGET", COLORS['BLUE'])
            if last_led_state != "WAITING":
                leds.fill(COLORS['BLUE']); leds.show(); last_led_state = "WAITING"

        time.sleep(0.1) 

except KeyboardInterrupt:
    print("\n🛑 얼굴 시스템 종료")
finally:
    leds.fill(COLORS['BLACK']); leds.show(); leds.close()
    update_lcd("SYSTEM OFF", COLORS['BLACK'])
    time.sleep(0.5); lcd.close()