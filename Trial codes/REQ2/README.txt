Placed all files in SD card
---------------------------
/SD card
│
├── adjustrayrect.py
├── main.py
├── nostm_db.mpy
├── stm_db.mpy
└── stm_db.mpy.mpy

Hardware Requirements Prerequisite
----------------------------------

- OpenMV H7 Plus Camera

- OpenMV IDE

- Stable lighting environment

- Chilli placement tray

- External hardware connected to GPIO outputs

PROCEDURE
---------

1. Connect the OpenMV camera to the OpenMV IDE.

2. Open calibration script:

	i. adjustrayrect.py

   Run only adjustrayrect.py script

   Adjust coordinates until the overlay matches the tray edges.

   Copy the final coordinates into main.py

   Calibration must be performed after the camera mounting position is finalized. Also please adjust the distance of 13 cm (130 mm)from Tray to camera lens

3. Run the script main.py 
Note: To start the test, keep the tray empty for 1 or 2 seconds to train the empty tray

4. GPIO Output Mapping
	P0 → Stem Present Signal
	P1 → Stem Absent Signal

