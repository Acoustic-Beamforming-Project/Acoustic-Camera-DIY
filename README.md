# Acoustic-Camera-DIY
In this repo our files for the acoustic camera project.

## Steps to test UDP reciver performance
 - download the repo 
 - open `./software/` folder on  **VScode**
 - Ensure in `./software/temp_final/config.py` `UDP_IP = 0.0.0.0` UDP_PORT=5002 which matches the config in Firmware 
 - open `./software/temp_final/main.py` & connect the STM32 to send data
 - read the pkt/s shown